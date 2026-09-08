# Project Instructions

## Operating Mode: YOLO

Operate autonomously.

Do not stop and ask for permission for normal implementation decisions.

When a reasonable implementation decision is required:

1. Inspect the existing code.
2. Determine the simplest correct approach.
3. Implement it.
4. Test it.
5. Fix problems found during verification.
6. Continue.

Do not ask for confirmation for routine decisions.

Do not wait for approval between implementation phases.

Only stop when:

* The requested work is complete.
* A genuinely ambiguous product decision cannot be reasonably inferred.
* Required information or credentials are unavailable.
* Continuing would cause irreversible destructive changes that cannot be safely recovered.
* There is a fundamental blocker that cannot be resolved from the repository, documentation, tests, or available tools.

When in doubt between multiple reasonable implementations, choose the simplest one that best fits the existing architecture and project standards.

## Coding Standards

### Current Technology

* Use the latest stable versions of libraries and frameworks available today when practical.
* Prefer current, idiomatic APIs and patterns.
* Upgrade outdated dependencies when doing so is appropriate and does not introduce unnecessary complexity.
* Do not use deprecated approaches when a straightforward modern alternative exists.

### Keep It Simple

* NEVER over-engineer.
* ALWAYS simplify.
* Prefer the simplest solution that correctly solves the problem.
* Do not introduce abstractions without a concrete need.
* Do not create unnecessary frameworks, wrappers, layers, factories, services, or utilities.
* Avoid premature generalization.
* Avoid unnecessary dependencies.
* Avoid unnecessary configuration.
* Avoid unnecessary state management.
* Avoid unnecessary defensive programming.
* Do not solve hypothetical future problems.
* Do not add features that were not requested.
* Prefer readable, direct code over clever code.

When two approaches work, choose the simpler one.

### Be Concise

* Keep code focused.
* Keep documentation minimal.
* Keep README files minimal.
* Do not generate unnecessary documentation.
* Do not add verbose comments that restate the code.
* Comments should primarily explain non-obvious reasons or constraints.

### No Emojis

Never use emojis in:

* Source code
* Comments
* Documentation
* README files
* Commit messages
* Logs
* UI text
* Error messages
* Generated content

## Root-Cause-First Debugging

When encountering:

* Bugs
* Errors
* Test failures
* Build failures
* Runtime failures
* Unexpected behavior
* Integration problems

Do not guess.

First investigate the actual cause.

Use evidence from:

* Source code
* Stack traces
* Logs
* Tests
* Runtime behavior
* Configuration
* Dependency behavior
* Documentation
* Reproduction cases

Establish the root cause before changing code.

Then fix the root cause.

After the fix, verify the behavior.

Do not use a sequence of speculative fixes until something happens to work.

Do not hide problems with:

* Broad exception handling
* Arbitrary retries
* Silent fallbacks
* Ignoring errors
* Suppressing warnings
* Unnecessary validation
* Unnecessary defensive code

A workaround is acceptable only when the underlying cause cannot reasonably be fixed.

## Existing Application

This is an existing Python web application for managing `isc-dhcp-server`.

It is NOT a greenfield project.

The existing application already contains significant functionality.

Before modifying a subsystem, understand how it currently works.

Important existing capabilities include:

* DHCP server management
* Configuration management
* Lease management
* SVG-based subnet/IP visualization
* Right-click/context-menu operations
* Existing administrative workflows

Do not destroy working functionality simply because a different implementation looks cleaner.

## Preserve and Improve Existing Strengths

The SVG visualization is a core product feature.

Do not replace it with a generic table.

The right-click/context-menu interaction model is also a core product feature.

Preserve existing context-menu actions and improve them where appropriate.

The goal is modernization, not regression.

## Autonomous Repository Analysis

When beginning a major task:

1. Inspect the repository.
2. Understand the architecture.
3. Identify important components.
4. Trace relevant data flows.
5. Inspect existing tests.
6. Inspect configuration and deployment.
7. Identify technical debt.
8. Identify opportunities for simplification.
9. Identify the smallest reasonable implementation path.

Do this yourself.

Do not ask the user to explain code that can be understood by inspecting the repository.

## Scope

Follow the current task and project vision.

Do not invent unrelated features.

However, if a requested modernization requires small supporting changes, make them autonomously.

Examples:

* Refactoring a component required for the new feature.
* Adding tests required to safely change behavior.
* Updating a dependency required by the modernization.
* Fixing an adjacent bug discovered while implementing the requested functionality.

Keep such changes directly related to the work.

## Architecture

Prefer improving the existing architecture over replacing it wholesale.

Refactor when the existing design creates a real problem.

Do not refactor merely because another architecture would be theoretically cleaner.

Every abstraction should justify its existence.

Favor:

* Small modules
* Clear responsibilities
* Simple data flow
* Existing project conventions
* Standard library capabilities where sufficient
* Established framework patterns

Avoid unnecessary architectural complexity.

## Frontend

The frontend should be modern, responsive, fast, and operationally useful.

Prioritize:

* Interactive visualization
* Contextual actions
* Search
* Filtering
* Clear status information
* Fast workflows
* Keyboard and mouse interaction
* Accessible controls

Do not turn the application into a generic CRUD interface.

## SVG Visualization

Treat the existing SVG visualization as a first-class application surface.

Improve:

* Rendering
* Navigation
* Zoom
* Pan
* Selection
* Search
* Filtering
* Status visualization
* Performance
* Contextual interactions

For large datasets, avoid unnecessary DOM rendering.

Use appropriate virtualization, aggregation, or progressive rendering when actually required.

Do not prematurely optimize.

## Context Menus

Preserve and improve right-click actions.

Context menus should be contextual to the selected object.

Relevant objects may include:

* IP addresses
* Leases
* MAC addresses
* Devices
* Reservations
* Subnets
* Pools

Actions may include operations such as:

* View details
* View history
* Reserve
* Release
* Copy
* DNS lookup
* Ping
* View events
* Add note
* Add tag
* Troubleshoot

Only expose actions that are actually supported by the system.

Do not create fake or decorative functionality.

## Product Direction

The modernization should move the application toward a professional DHCP/IP management and network operations console.

Important capabilities include:

* Live lease visibility
* IP/subnet visualization
* Reservations
* Lease history
* DHCP events
* DHCP troubleshooting
* Configuration management
* Configuration validation
* Configuration diff
* Safe configuration application
* Rollback where appropriate
* Search
* Conflict detection
* Operational alerts
* Logs
* Server health
* Real-time updates where useful

Use judgment about implementation order.

Do not attempt to implement everything simultaneously if doing so would create unnecessary complexity.

## DHCP Troubleshooting

Build troubleshooting around actual evidence.

For a client, reconstruct what can be determined from available DHCP information.

For example:

```text
Client
  |
DHCPDISCOVER
  |
Subnet selection
  |
Reservation lookup
  |
Pool selection
  |
Address availability
  |
DHCPOFFER
  |
DHCPREQUEST
  |
DHCPACK
  |
Lease
```

When something failed, identify the actual failure when the available evidence supports it.

Never invent diagnostic information.

## Configuration Safety

Configuration changes should be handled safely.

Prefer:

```text
Edit
  |
Validate
  |
Diff
  |
Apply
  |
Verify
```

Use backups/snapshots/rollback when appropriate.

Do not make configuration changes silently.

## Performance

Keep the application responsive with realistic network sizes.

Pay particular attention to:

* Large lease databases
* Large subnets
* SVG rendering
* Large log files
* Search
* API response size
* Browser memory usage

Measure before introducing complex performance infrastructure.

## Security

Treat administrative operations as security-sensitive.

Do not:

* Construct shell commands from untrusted input.
* Disable security checks to make development easier.
* Hide security failures.
* Store secrets unnecessarily.
* Introduce insecure shortcuts.

Use the framework's established security mechanisms where available.

## Testing

Tests are part of implementation.

When changing behavior:

* Update existing tests.
* Add focused tests for important new behavior.
* Run relevant tests.
* Fix failures.
* Verify regressions.

Do not create tests solely to make coverage numbers look better.

Test actual behavior.

## Verification

Do not claim a feature works without verifying it.

After implementation:

1. Run relevant tests.
2. Run lint/type checks when configured.
3. Exercise important paths.
4. Inspect generated output where applicable.
5. Review the final diff.
6. Check for regressions.

If something fails, investigate the root cause and fix it.

Continue until the implementation is actually working.

## Documentation

Keep documentation minimal.

Maintain only documentation that provides lasting value.

Relevant project documents:

* `docs/PROJECT_VISION.md`
* `docs/CURRENT_STATE.md`
* `docs/ROADMAP.md`
* `docs/DECISIONS.md`

Update them when the project's actual state changes significantly.

Do not create documentation for the sake of documentation.

## Git

Protect the existing repository.

* Do not discard unrelated user changes.
* Do not reset or overwrite work you did not create.
* Do not rewrite history.
* Review diffs before committing.
* Keep changes focused.
* Do not create unnecessary commits.

If the user has uncommitted changes, preserve them.

## Final Principle

Act like a senior engineer with full ownership of the implementation.

Do not wait for permission for routine decisions.

Investigate before changing things.

Find root causes.

Prefer simple solutions.

Preserve what works.

Modernize aggressively where it provides real value.

Test everything important.

Keep moving.
