# Change-focused projection detail

Reviewer profile v2 asks for the smallest source-supported composition that
makes an architectural change visible at comparable depth on both sides.
For extraction, it names the affected parts and preserves their identities as
their containing boundary changes. The root must encompass both boundaries.
If the new shared layer has an established name, it remains an explicit parent
of its parts. The common application root must not replace that layer. An owner
is a declared node with its own identity and correct-side source references.
New shared files do not make an existing responsibility absent on the before
side: inline and feature-local implementations provide its before references.
For an executable refactor, accompanying documentation supports code boundaries
rather than becoming extra Knowledge/Documentation responsibilities.
Containment describes implementation ownership at this scope; it does not
declare consumer usage, runtime order, or behavioral equivalence.

A newly added opaque `DesignSystem` node can hide the extraction. A file/type
inventory is also unsuitable. Unchanged structure is valid when that is all
the evidence supports; neither the number of nodes nor colored lines is a
quality target. Shared parts are represented once, with consumer context in
the source evidence and explanations.

## SessionMonitor #117 replay

The [reviewed PR](https://github.com/SoundBlaster/SessionMonitor/pull/117)
extracts common visual components from context-insight UI code. The original
projection showed only an added `DesignSystem` leaf. An intermediate v2 draft
exposed the parts but flattened them into the application root. The revised
profile preserves the named shared owner and its extracted composition:

```diff
 MonitorMacApplication
   ContextAnatomyFeature
     ContextInsightPresentation
     ContextInsightCardComposition
-    AdaptiveCardHeader
-    EvidenceDisclosure
-    InsightMetric
-    InsightBadge
-    DesignCardSurface
+  DesignSystem
+    AdaptiveCardHeader
+    EvidenceDisclosure
+    InsightMetric
+    InsightBadge
+    DesignCardSurface
```

These are inferred responsibilities, not one node per Swift type. Before-side
references identify badge/metric definitions and header/disclosure/surface
composition in the feature. After-side references identify their shared
implementations. Feature-specific content, formatting and state remain in
`ContextAnatomyFeature`; moving a visual responsibility does not assert that
the feature stopped displaying it.
An ordinary text diff adds only one parent line: the five child lines keep
their names and indentation. Compact renderer v5 instead matches lines together
with their containing paths, exposing removal from the old branch and addition
under the new owner. This remains a valid unified patch of the same two files;
it deliberately favors visible ownership changes over the shortest text edit.
These display keys do not establish cross-revision identity. The compiler's IR diff
reports five removed feature paths and an added `DesignSystem` subtree. Reading
those as five relocations relies on the paired identity map and source evidence;
it is not a compiler-proven move operation.

Compact renderer v5 includes the full context of projections up to 40 lines,
so the root, named owner and all its parts stay visible in this small example.
Larger projections retain the usual focused diff context.

The replay used the same 16 selected source records, source-byte budget and
pinned revisions as the published original:

- Before: `19d9ce289a07b4c93a3ff304e8bc9f70e403ebd0`.
- After: `fa46d925d0c32ac6fad639f43cbe98bf065842b5`.
- Codex: `gpt-6-luna`, reasoning `medium`; same CLI executable fingerprint.
- Same Hypercode compiler SHA256:
  `6503784100372b8fe93d0a794caf80bfbfc47da880874b2b9177267d34a26b9f`.
- Final result passed the compiler, reference and identity checks on one model
  attempt. Intermediate drafts produced an opaque destination, unchanged tree,
  flattened owner, or missing before-side primitives and were not accepted as
  the final example. Invalid parent IDs and duplicate references were rejected
  locally; the schema now explains those fields and before-side presence more
  explicitly without relaxing the validator.

This is a worked example, not a model reliability measurement. Compilation
checks the declared composition and references; it does not prove the
interpretation, runtime behavior or visual parity. Earlier preview bundles and
publication plans are retained as historical evidence. Updating a comment requires operator
review and publication authorization.

The expanded profile also consumes context budget. The shared HTTP default is
16384 for both the Python API and CLI, so the existing small repair fixtures can
exercise the default configuration. A loaded model must support the configured
context. The conservative preflight and explicit overrides remain in force;
budget-boundary tests still reject oversized input before a request is sent.
