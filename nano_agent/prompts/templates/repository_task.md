<task>
<request>{user_request}</request>
<repository>{repo_url}</repository>
</task>

Work on this task, not a generic repository audit. At the first turn, clone the repository if the
workspace is not ready. Then inspect only enough repository structure, instructions, code, and
tests to choose the next evidence-producing action.

If the user gives a concrete file, error, command output, issue, or expected behavior, start from
that specific evidence instead of broad exploration. If the request describes a failure or
regression, prioritize reproducing or tracing that behavior. When a code change is requested,
continue through implementation and relevant verification rather than stopping after diagnosis.
If the request is analysis-only, do not modify the repository.
