"""Native Codex session adapter for the ImageProvider protocol.

The caller must run this in an appropriately isolated server account: Codex is
an agent, and its sandbox is not a substitute for service-level isolation.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
import signal
import stat
import subprocess
import tempfile
import threading

from .image_generation import GeneratedImage

MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_RESPONSE_BYTES = 64 * 1024


class CodexImageError(RuntimeError):
    """A redacted session or generated-image validation failure."""

    def __init__(self, message, code='IMAGE_PROVIDER_FAILED'):
        super().__init__(message)
        self.code = code


def _read_image(root: Path, reported: str) -> GeneratedImage:
    # Open every component relative to an already opened directory, without
    # following symlinks. No path supplied by the model can escape this root.
    try:
        path = Path(reported)
        parts = path.relative_to(root).parts
        if not parts or any(p in ('', '.', '..') for p in parts):
            raise ValueError
        directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            for part in parts[:-1]:
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
                os.close(directory)
                directory = child
            fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
            try:
                info = os.fstat(fd)
                if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= MAX_IMAGE_BYTES:
                    raise ValueError
                with os.fdopen(fd, 'rb', closefd=False) as source:
                    data = source.read(MAX_IMAGE_BYTES + 1)
                if len(data) != info.st_size:
                    raise ValueError
            finally:
                os.close(fd)
        finally:
            os.close(directory)
        if data.startswith(b'\x89PNG\r\n\x1a\n'):
            mime = 'image/png'
        elif data.startswith(b'\xff\xd8\xff'):
            mime = 'image/jpeg'
        else:
            raise ValueError
        return GeneratedImage(data, mime)
    except (OSError, ValueError, TypeError):
        raise CodexImageError('Generated image failed validation.', 'IMAGE_OUTPUT_INVALID') from None


class CodexImageProvider:
    """Run one bounded Codex session per image using the built-in image_gen tool.

    codex_home is the existing service account's Codex home; this adapter does
    not inspect credentials. A working Codex installation and session are needed.
    """

    def __init__(self, *, codex_home=None, executable='codex', timeout=300):
        if not isinstance(timeout, (int, float)) or not 0 < timeout <= 3600:
            raise ValueError('Invalid Codex timeout.')
        self.codex_home = Path(codex_home or os.environ.get('CODEX_HOME') or Path.home() / '.codex').absolute()
        self.executable = os.fspath(executable)
        self.timeout = timeout

    def generate(self, prompt: str) -> GeneratedImage:
        if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 10000:
            raise ValueError('Invalid image prompt.')
        instruction = (
            'Use the built-in image_gen tool to generate exactly one image for the request below; '
            'call the tool once and do not create variations. '
            'Do not use API or CLI fallbacks. Return only a JSON object with one key "path", '
            'whose value is the absolute path of the generated file under CODEX_HOME/generated_images. '
            'If the image_gen tool is unavailable, return {"error":"IMAGE_TOOL_UNAVAILABLE"}. '
            'If generation produces no file, return {"error":"IMAGE_NO_RESULT"}. '
            'Never return an empty path or claim success without generating a real file. '
            'Do not return any other text.\n\nImage request:\n' + prompt
        )
        env = os.environ.copy()
        env['CODEX_HOME'] = str(self.codex_home)
        generated_root=self.codex_home/'generated_images'
        previous_threads={p.name for p in generated_root.iterdir()} if generated_root.is_dir() else set()
        with tempfile.TemporaryDirectory(prefix='codex-image-') as workspace:
            try:
                proc = subprocess.Popen(
                    [self.executable, 'exec', '--skip-git-repo-check', '--ephemeral', '--json',
                     '--sandbox', 'read-only', '-C', workspace, '-'],
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                    env=env, start_new_session=True,
                )
            except OSError:
                raise CodexImageError('Unable to start Codex session.', 'IMAGE_START_FAILED') from None
            output = bytearray()
            overflow = threading.Event()

            def drain():
                while True:
                    chunk = proc.stdout.read(8192)
                    if not chunk:
                        break
                    if len(output) + len(chunk) > MAX_RESPONSE_BYTES:
                        overflow.set()
                        try:
                            os.killpg(proc.pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                        break
                    output.extend(chunk)

            reader = threading.Thread(target=drain, daemon=True)
            reader.start()
            def send():
                try:
                    proc.stdin.write(instruction.encode('utf-8'))
                    proc.stdin.close()
                except OSError:
                    pass

            writer = threading.Thread(target=send, daemon=True)
            writer.start()
            try:
                proc.wait(timeout=self.timeout)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                proc.wait()
                raise CodexImageError('Codex image session timed out.', 'IMAGE_TIMEOUT') from None
            finally:
                writer.join(timeout=1)
                reader.join(timeout=1)
                if not reader.is_alive():
                    proc.stdout.close()
            if overflow.is_set():
                raise CodexImageError('Codex image session response exceeded the limit.', 'IMAGE_RESULT_TOO_LARGE')
            if proc.returncode != 0:
                raise CodexImageError('Codex image session failed.', 'IMAGE_SESSION_FAILED')
            try:
                # --json supplies the actual session identity. Recover native tool
                # output from that session only, never from the newest shared file
                # or solely from the model's final (sometimes incorrect) reply.
                try:
                    decoded=json.loads(output)
                except ValueError:
                    decoded=None
                if isinstance(decoded,dict) and set(decoded) in ({'path'},{'error'}):
                    response=decoded  # Legacy CLI result compatibility.
                else:
                    events=[json.loads(line) for line in output.splitlines() if line.strip()]
                    threads={e.get('thread_id') for e in events if isinstance(e,dict) and e.get('type')=='thread.started'}
                    if len(threads)!=1:
                        raise ValueError
                    thread=next(iter(threads))
                    if not isinstance(thread,str) or not re.fullmatch(r'[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}',thread) or thread in previous_threads:
                        raise ValueError
                    folder=generated_root/thread
                    if folder.is_symlink():
                        raise ValueError
                    candidates=sorted((p for p in folder.rglob('*') if p.suffix.lower() in ('.png','.jpg','.jpeg') and p.is_file()),
                                      key=lambda p:p.stat().st_mtime) if folder.is_dir() else []
                    messages=[e['item'].get('text','') for e in events if isinstance(e,dict) and e.get('type')=='item.completed'
                              and isinstance(e.get('item'),dict) and e['item'].get('type')=='agent_message']
                    if candidates:
                        # Every candidate is in this new session's own folder. If the model
                        # generated more than one, use the image it reported, else the latest.
                        try:
                            reported=json.loads(messages[-1]).get('path') if messages else None
                        except (ValueError,AttributeError):
                            reported=None
                        chosen=next((p for p in candidates if isinstance(reported,str)
                                     and os.path.normpath(reported)==os.path.normpath(str(p))),candidates[-1])
                        return _read_image(generated_root,str(chosen))
                    if not messages:
                        raise ValueError
                    response=json.loads(messages[-1])
                    if isinstance(response,dict) and response.get('path'):
                        # A path from another session cannot stand in for this one.
                        Path(response['path']).relative_to(folder)
                if isinstance(response, dict) and set(response) == {'error'}:
                    code = response['error']
                    if isinstance(code, str) and code in {'IMAGE_TOOL_UNAVAILABLE', 'IMAGE_NO_RESULT'}:
                        raise CodexImageError('Codex did not generate an image.', code)
                if not isinstance(response, dict) or set(response) != {'path'} or not isinstance(response['path'], str):
                    raise ValueError
                if not response['path'].strip():
                    raise CodexImageError('Codex returned no generated image.', 'IMAGE_NO_RESULT')
            except (ValueError, UnicodeDecodeError):
                raise CodexImageError('Codex image session returned an invalid response.', 'IMAGE_INVALID_RESPONSE') from None
            return _read_image(self.codex_home / 'generated_images', response['path'])
