# Final Report Quality

## Problem

The Django stress rerun completed successfully, but `report.md` only contained a high-level summary. It did not include the full structured report requested by the user: key files, risks, evidence paths, and uncertainty for each direction.

## Cause

- Subagent results were delivered, but the main Agent summarized them too aggressively in `finish_run`.
- One subagent returned a weak `output` value: `See the structured analysis report above...`.
- The main Agent treated missing structured content as a reason to read source files again instead of using a reliable subagent result artifact.

## Fix Plan

- Strengthen completion guidance so `finish_run.resolution` must contain the user-facing final report body for analysis-only tasks.
- Ensure subagent success results preserve the full `completion_report.resolution` in persistence.
- When a compacted result includes `full_result`, teach the main Agent to use that artifact reference instead of assuming data is missing.
- Add a test where multiple background subagents return structured reports and the parent final report must include each section.

## Acceptance Criteria

- Final `report.md` includes the requested structured analysis, not only a summary.
- The main Agent does not perform unnecessary source reads solely because a subagent result was compacted.
- The report clearly separates each delegated direction and includes evidence and uncertainty.
