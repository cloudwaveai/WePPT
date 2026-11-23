"""Review native scene renders using pinned PPTAgent image tools, never PPTX finalize."""
import hashlib
import json
import sys
from pathlib import Path

COMMIT = "acf703e28be98f57b7351a2fddf48325f579f252"
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "data" / "upstream-skills" / "pptagent" / COMMIT / "scripts"))
from pptagent_runtime.core import _contact_sheets
from pptagent_runtime.visual import SYSTEM_PROMPT, validate_review


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inside(directory, name):
    path = (directory / name).resolve()
    if not path.is_relative_to(directory):
        raise ValueError("image or record escapes review directory")
    return path


def main(request):
    directory = Path(request["directory"]).resolve(strict=True)
    manifest = request["manifest"]
    ids = [item["pageId"] for item in manifest]
    if not ids or len(ids) > 100 or len(set(ids)) != len(ids):
        raise ValueError("invalid review manifest")
    if [item["number"] for item in manifest] != list(range(1, len(ids) + 1)):
        raise ValueError("manifest must follow rendered page order")
    pages = [inside(directory, f"page-{i + 1}.png") for i in range(len(ids))]
    hashes = {ids[i]: digest(path) for i, path in enumerate(pages)}
    fingerprint = hashlib.sha256(json.dumps({"images": hashes, "reference": digest(inside(directory, request["referenceImage"])) if request.get("referenceImage") else None, "scene": request["sceneFingerprint"]}, sort_keys=True).encode()).hexdigest()
    state_path = inside(directory, "pptagent-scene-state.json")
    if request["operation"] == "prepare":
        out = inside(directory, "pptagent-contacts")
        out.mkdir(exist_ok=True)
        contacts = _contact_sheets(pages, out)
        state = {"provider": "PPTAgent native-scene visual review", "commit": COMMIT,
                 "sourceFingerprint": fingerprint, "imageHashes": hashes,
                 "contactHashes": {str(p): digest(p) for p in contacts}, "manifest": manifest}
        state_path.write_text(json.dumps(state), encoding="utf-8")
        return {**state, "systemPrompt": SYSTEM_PROMPT, "contactSheets": [str(p) for p in contacts]}
    if request["operation"] != "record":
        raise ValueError("unsupported operation")
    state = json.loads(state_path.read_text(encoding="utf-8"))
    if state["sourceFingerprint"] != fingerprint or state["manifest"] != manifest:
        raise ValueError("source images or scene changed after preparation")
    for name, expected in state["contactHashes"].items():
        if digest(inside(directory, name)) != expected:
            raise ValueError("contact image changed after preparation")
    reviews = [validate_review(review) for review in request["reviews"]]
    checked = set()
    for review in reviews:
        coverage = review.get("checkedPageIds")
        if not isinstance(coverage, list) or any(i not in ids for i in coverage):
            raise ValueError("invalid checked page IDs")
        checked.update(coverage)
        if any(issue["slide"] > len(ids) for issue in review["issues"]):
            raise ValueError("invalid review slide")
    complete = checked == set(ids)
    status = "unjudgeable" if not complete or any(r["verdict"] == "unjudgeable" for r in reviews) else "fail" if request.get("programErrors") or any(r["verdict"] == "fail" for r in reviews) else "pass"
    result = {**state, "checkedPageIds": [i for i in ids if i in checked], "fullSizePageIds": request["fullSizePageIds"], "status": status, "finalized": False}
    inside(directory, "pptagent-scene-review.json").write_text(json.dumps({"evidence": result, "reviews": reviews}, ensure_ascii=False), encoding="utf-8")
    return result


if __name__ == "__main__":
    try:
        print(json.dumps(main(json.load(sys.stdin)), ensure_ascii=False))
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
