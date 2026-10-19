# Change-focused projection detail

Reviewer profile v2 asks for the smallest source-supported composition that
makes an architectural change visible at comparable depth on both sides.
For extraction, it names the affected parts and preserves their identities as
their containing boundary changes. The root must encompass both boundaries.
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
projection showed only an added `DesignSystem` leaf. The final v2 replay shows
the previously feature-owned parts at the common UI scope:

```diff
 MonitorUIComposition
   ContextInsightFeatureUI
-    StatusBadgePresentation
-    LabeledMetricPresentation
-    AdaptiveCardHeader
-    EvidenceDisclosurePresentation
-    CardSurfacePresentation
+  StatusBadgePresentation
+  LabeledMetricPresentation
+  AdaptiveCardHeader
+  EvidenceDisclosurePresentation
+  CardSurfacePresentation
```

These are inferred responsibilities, not one node per Swift type. Before-side
references identify badge/metric definitions and header/disclosure/surface
composition in the feature. After-side references identify their shared
implementations. Feature-specific content, formatting and state remain in
`ContextInsightFeatureUI`; moving a visual responsibility does not assert that
the feature stopped displaying it.

The replay used the same 16 selected source records, source-byte budget and
pinned revisions as the published original:

- Before: `19d9ce289a07b4c93a3ff304e8bc9f70e403ebd0`.
- After: `fa46d925d0c32ac6fad639f43cbe98bf065842b5`.
- Codex: `gpt-6-luna`, reasoning `medium`; same CLI executable fingerprint.
- Same Hypercode compiler SHA256:
  `6503784100372b8fe93d0a794caf80bfbfc47da880874b2b9177267d34a26b9f`.
- Final result passed the compiler, reference and identity checks on one model
  attempt. Two intermediate prompt drafts produced an opaque destination or
  unchanged tree and were discarded.

This is a worked example, not a model reliability measurement. Compilation
checks the declared composition and references; it does not prove the
interpretation, runtime behavior or visual parity. The old bundle and published
comment remain intact. A revised comment requires separate operator review and
publication authorization.

The expanded profile also consumes context budget. HTTP repair fixtures reserve
16384 units where a repair is expected; the production default and conservative
preflight remain unchanged. Budget-boundary tests still reject oversized input
before a request is sent.
