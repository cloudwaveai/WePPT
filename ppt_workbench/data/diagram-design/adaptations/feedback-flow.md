# We-PPT feedback flow adaptation

Project adaptation of diagram-design's semantic-first method. The upstream Loop
reference describes a shared-state hub with an outer ring. This guide covers
feedback flows that do not establish such a hub. Keep the upstream files intact.

## Meaning before geometry

1. Read the original text, page purpose and notes. Identify operations, stored
   artifacts and relationships. A verb such as “筛选与保存” describes an operation;
   do not turn it into a shared-store entity just to fill a central slot.
2. Identify the main directed path and the exact feedback destination. Feedback
   may return to an intermediate step. Do not automatically connect last to first.
3. Draw only relationships supported by the content. A mentioned memory or data
   concept alone does not establish an extra hub or links to every step.
4. If the source leaves a real factual relationship unknown, disclose that
   ambiguity in the assistant reply. Do not invent a connection to complete a ring.

## Editable visual construction

- Choose the arrangement from the relationships and text sizes: a horizontal or
  folded path with a return lane, a vertical flow, or another legible arrangement.
  There is no fixed station count, center node, or equal-slot requirement.
- Use native editable objects. All original words and images remain intact.
- Use native line startArrow/endArrow booleans on the final connector segment,
  pointing into the destination boundary. startArrow points to (x,y), endArrow to
  (x+w,y+h). Do not use floating arrow text. For left/up use startArrow.
- Route feedback through a separate empty lane. No line may pass through an
  unrelated node, obscure text, imply an unsupported shortcut, or terminate on
  the wrong card. Do not add a line purely to make the diagram symmetric.
- Preserve the chosen reference's useful color and typography, not its topology.
- No invented labels, duplicated steps, explanatory footnotes, or mandatory hub.

## Review

Trace every visible arrow from source to destination against the original content.
Fix incorrect paths and node placement together. Adding arrows to a wrong topology
does not repair it. When the original relationship is clear, correct the candidate
without asking the user to approve an already-specified fact. If a local patch
cannot express the full correction, return a complete replacement of this candidate.
