<task>
<request>{user_request}</request>
<repository>{repo_url}</repository>
</task>

Work on this task, not a generic repository audit. At the first turn, clone the repository if the
workspace is not ready. Then inspect only enough repository structure, instructions, code, and
tests to choose the next evidence-producing action.

After cloning, make a lightweight routing decision before deep reading:

- If the request is narrow, execute directly.
- If the request contains multiple meaningful directions, user-listed items, dependencies, or a
  broad modular analysis, decide whether persistent Tasks are useful.
- If independent directions are read-heavy and mostly investigative, create bounded Tasks and
  delegate them to background subagents instead of reading every direction in the main Agent.
- Use only minimal structure discovery for this routing pass. Do not read full source or test
  files for every candidate direction before deciding the route.

If the user gives a concrete file, error, command output, issue, or expected behavior, start from
that specific evidence instead of broad exploration. If the request describes a failure or
regression, prioritize reproducing or tracing that behavior. When a code change is requested,
continue through implementation and relevant verification rather than stopping after diagnosis.
If the request is analysis-only, do not modify the repository.
