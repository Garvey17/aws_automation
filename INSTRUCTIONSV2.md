# Build AIDeploy V1 — Ephemeral AWS Deployment CLI for FastAPI Projects

You are an experienced Python, AWS, Docker, DevOps, and CLI engineer.

Build **Version 1 of AIDeploy**, a personal deployment CLI designed specifically for deploying **FastAPI backend applications to AWS at extremely low cost**, primarily for temporary demonstrations of AI-engineering portfolio projects.

The goal is NOT to build a general-purpose deployment platform.

The goal is:

> Developer runs `aideploy up` → FastAPI application is built, deployed to AWS, health-checked, and given a public endpoint.

Then:

> Developer runs `aideploy down` → resources created by AIDeploy are safely destroyed.

The system must prioritize:

* simplicity
* deterministic behavior
* safety
* low cost
* reproducibility
* clean architecture
* testability
* clear error messages

Do NOT add AI/LLM functionality in V1.

---

# 1. Core V1 requirements

Implement these commands:

```bash
aideploy init
aideploy up
aideploy down
aideploy status
aideploy logs
```

The minimum lifecycle is:

```text
FastAPI project
      ↓
aideploy init
      ↓
aideploy.yaml
      ↓
aideploy up
      ↓
validate
      ↓
build
      ↓
deploy
      ↓
health check
      ↓
public API endpoint
```

And:

```text
aideploy down
      ↓
identify AIDeploy resources
      ↓
destroy
      ↓
verify cleanup
```

---

# 2. Technology requirements

Use:

* Python 3.12+
* Typer for CLI
* Pydantic/Pydantic Settings for configuration and validation
* boto3 for AWS API interaction
* Docker for application packaging
* pytest for testing
* Ruff for linting
* mypy where practical
* standard Python logging

Do not introduce unnecessary frameworks.

The project should be installable locally with:

```bash
pip install -e .
```

and preferably:

```bash
pipx install .
```

---

# 3. Recommended project structure

Use a clean architecture similar to:

```text
aideploy/
├── pyproject.toml
├── README.md
├── LICENSE
├── .gitignore
├── tests/
│
├── src/
│   └── aideploy/
│       ├── __init__.py
│       ├── cli/
│       │   ├── __init__.py
│       │   └── main.py
│       │
│       ├── config/
│       │   ├── __init__.py
│       │   ├── loader.py
│       │   └── schema.py
│       │
│       ├── detector/
│       │   ├── __init__.py
│       │   └── fastapi.py
│       │
│       ├── docker/
│       │   ├── __init__.py
│       │   └── builder.py
│       │
│       ├── aws/
│       │   ├── __init__.py
│       │   ├── client.py
│       │   ├── iam.py
│       │   ├── compute.py
│       │   ├── api_gateway.py
│       │   ├── storage.py
│       │   └── cost.py
│       │
│       ├── deployment/
│       │   ├── __init__.py
│       │   ├── planner.py
│       │   ├── deployer.py
│       │   ├── destroyer.py
│       │   └── health.py
│       │
│       ├── state/
│       │   ├── __init__.py
│       │   └── manager.py
│       │
│       └── exceptions.py
│
└── tests/
    ├── unit/
    └── integration/
```

You may adjust the structure if there is a strong architectural reason, but maintain separation between:

* CLI
* configuration
* project detection
* Docker
* AWS infrastructure
* deployment lifecycle
* state management

The CLI must NOT contain AWS implementation logic.

---

# 4. Deployment architecture

For V1, use a **containerized FastAPI deployment architecture**.

However, before implementing the AWS layer, evaluate the currently supported AWS services and choose the simplest architecture that satisfies these constraints:

1. FastAPI must run publicly.
2. It must support Docker/containerized deployment.
3. It must be suitable for intermittent portfolio traffic.
4. It should minimize idle costs.
5. It must be straightforward to destroy completely.
6. It must not require unnecessary infrastructure.
7. It must be automatable with boto3/IaC.
8. The implementation must be realistic for a personal project.

Do not blindly assume that a specific AWS service is free.

The implementation must explicitly document the expected AWS costs and free-tier assumptions.

If the chosen architecture has unavoidable or potentially billable components, the Cost Guard must detect them and require explicit confirmation.

---

# 5. Cost safety is a first-class requirement

This is NOT optional.

AIDeploy is intended for portfolio projects where the developer wants to keep infrastructure costs as close to zero as reasonably possible.

Never make the false claim that AWS deployment is guaranteed to cost $0.

Instead, implement a **Cost Guard**.

Before creating infrastructure, AIDeploy must produce a resource plan:

```text
Deployment plan
────────────────────────────

Project: my-api

Resources:
✓ ...
✓ ...
⚠ ...

Potentially billable:
...

Cost policy:
max_monthly = $0

Deployment:
ALLOWED / BLOCKED
```

The deployment must be blocked when:

* a resource is explicitly disallowed by the configured policy
* the system cannot determine the cost characteristics of a required resource
* required AWS permissions are missing
* the deployment architecture violates the user's configured policy

Never silently continue when the cost state is uncertain.

---

# 6. Resource tagging

Every AWS resource created by AIDeploy must receive identifying metadata where AWS supports tagging.

Use tags such as:

```text
ManagedBy=AIDeploy
Project=<project-name>
DeploymentId=<deployment-id>
Environment=portfolio
```

The exact tag keys may be centralized as constants.

This is essential for safe destruction.

---

# 7. Destruction safety

`aideploy down` must NEVER blindly delete arbitrary AWS resources.

It may only delete resources that AIDeploy created and can positively identify.

Use deployment state plus AIDeploy tags/identifiers.

Before destruction:

```text
Deployment: dep_123
Project: rag-api

Resources to destroy:
- ...
- ...
- ...

Continue? [y/N]
```

Support:

```bash
aideploy down --yes
```

for non-interactive usage.

If state is missing or inconsistent, fail safely rather than guessing.

---

# 8. Configuration file

Implement:

```yaml
name: rag-api

runtime:
  python: "3.12"

app:
  entrypoint: "app.main:app"

health:
  path: "/health"

environment:
  - OPENAI_API_KEY
  - DATABASE_URL

deployment:
  strategy: "auto"

cost:
  max_monthly: 0
```

Use Pydantic models to validate the configuration.

Do not allow arbitrary unknown configuration to silently pass.

Provide useful validation errors.

---

# 9. Environment variables and secrets

AIDeploy must NOT automatically upload `.env` files to GitHub, Docker images, logs, or public storage.

Support environment variables through a safe mechanism.

At minimum:

```yaml
environment:
  - OPENAI_API_KEY
```

means:

> retrieve the value from the local deployment environment.

Do not print secret values.

Never output:

```text
OPENAI_API_KEY=sk-...
```

to logs.

Do not store secrets in the deployment state file.

Clearly document how users should provide secrets.

---

# 10. FastAPI detection

Implement basic deterministic project detection.

A project should be recognized as FastAPI based on evidence such as:

* `requirements.txt`
* `pyproject.toml`
* Python source files
* import/use of FastAPI
* configured application entrypoint

Example:

```python
from fastapi import FastAPI

app = FastAPI()
```

The detector should return structured information such as:

```python
ProjectInfo(
    framework="fastapi",
    python_version="3.12",
    entrypoint="app.main:app",
)
```

Do NOT use an LLM for detection.

---

# 11. Docker support

AIDeploy should support projects that already have a Dockerfile.

If no Dockerfile exists, generate a sensible default for a standard FastAPI project.

The generated Dockerfile should:

* use a slim Python base image
* install dependencies
* copy application code
* expose the configured port if appropriate
* run Uvicorn
* avoid development servers
* avoid embedding secrets

Allow the user to override the generated Dockerfile.

Do not overwrite an existing Dockerfile without explicit permission.

---

# 12. Docker image lifecycle

Implement:

```text
build image
      ↓
tag image
      ↓
deploy image
```

Use deterministic deployment IDs.

Example:

```text
rag-api:dep-20260927-abc123
```

Avoid relying on mutable tags such as only:

```text
latest
```

for deployment identity.

---

# 13. Deployment state

Maintain local state so AIDeploy knows what it created.

For example:

```text
.aideploy/
    state.json
```

State should include non-secret information such as:

```json
{
  "project": "rag-api",
  "deployment_id": "dep_123",
  "status": "running",
  "created_at": "...",
  "endpoint": "...",
  "resources": [],
  "expires_at": null
}
```

Do not store:

* API keys
* passwords
* secret values
* AWS secret access keys

State must be treated as disposable and reconstructable where possible.

---

# 14. Deployment lifecycle

Implement the deployment as explicit phases:

```text
VALIDATE
   ↓
DETECT
   ↓
PLAN
   ↓
COST_CHECK
   ↓
BUILD
   ↓
PROVISION
   ↓
DEPLOY
   ↓
HEALTH_CHECK
   ↓
SAVE_STATE
```

If any phase fails:

```text
deployment failed
      ↓
determine whether partial resources were created
      ↓
attempt safe cleanup
      ↓
report failure
```

Avoid leaving orphaned infrastructure.

---

# 15. Health checks

After deployment, call:

```text
GET /health
```

using the configured health path.

Support configurable timeout and retry behavior.

Example:

```yaml
health:
  path: "/health"
  timeout: 10
  retries: 5
```

A deployment should not be reported as successful merely because AWS accepted the resource creation.

The application must actually become reachable.

---

# 16. CLI UX

Commands should be clear and human-friendly.

Examples:

```bash
aideploy init
```

```text
✓ FastAPI project detected
✓ Generated aideploy.yaml
```

Then:

```bash
aideploy up
```

should show progress:

```text
AIDeploy

[1/7] Validating project       ✓
[2/7] Detecting FastAPI        ✓
[3/7] Building container       ✓
[4/7] Checking cost policy     ✓
[5/7] Provisioning AWS         ✓
[6/7] Deploying application    ✓
[7/7] Health check             ✓

Deployment successful.

Endpoint:
https://...
```

Use appropriate exit codes.

Successful command:

```text
0
```

Failure:

```text
non-zero
```

---

# 17. `aideploy status`

Show:

```text
Project: rag-api
Status: RUNNING

Deployment ID: dep_123
Created: ...
Endpoint: ...

Resources:
✓ ...

Expires:
Never
```

If nothing is deployed:

```text
Status: NOT DEPLOYED
```

---

# 18. `aideploy logs`

Provide logs from the chosen AWS runtime where technically supported.

Do not pretend logs exist if the chosen AWS architecture does not expose them in the required way.

Support options such as:

```bash
aideploy logs
aideploy logs --follow
```

if feasible.

---

# 19. `aideploy init`

When run in a FastAPI project:

```bash
aideploy init
```

should:

1. inspect the project
2. detect FastAPI
3. determine likely entrypoint
4. detect Python version if possible
5. create `aideploy.yaml`
6. explain any assumptions

Never silently overwrite an existing configuration.

---

# 20. AWS credentials

Do not create or manage AWS access keys automatically.

Use standard AWS credential resolution mechanisms supported by boto3.

Document support for:

* AWS CLI profiles
* environment variables
* IAM roles where applicable

Allow:

```bash
aideploy up --profile myprofile
```

if practical.

Never print credentials.

---

# 21. Testing requirements

Testing is mandatory.

Write unit tests for:

### Configuration

* valid configuration
* invalid configuration
* missing required values
* unknown fields

### Detection

* valid FastAPI project
* missing FastAPI
* missing entrypoint
* malformed project

### Docker

* Dockerfile generation
* existing Dockerfile preservation
* invalid configuration

### Cost Guard

* allowed resource
* blocked resource
* unknown resource
* zero-cost policy
* explicit override behavior

### State

* save
* load
* corrupted state
* missing state

### Deployment

Mock AWS APIs.

Do NOT require real AWS credentials for unit tests.

---

# 22. AWS integration tests

Separate real AWS integration tests from unit tests.

They should only run explicitly, for example:

```bash
pytest -m aws
```

Never make normal:

```bash
pytest
```

create AWS resources.

Use environment variables to enable integration testing.

Document cleanup procedures.

---

# 23. Failure scenarios

Explicitly test and handle:

* AWS credentials unavailable
* insufficient IAM permissions
* Docker unavailable
* Docker build failure
* invalid FastAPI entrypoint
* invalid configuration
* AWS API timeout
* partial AWS deployment
* health check failure
* missing state
* corrupted state
* resource already deleted
* deployment interrupted with Ctrl+C

The CLI should provide actionable errors.

Bad:

```text
Botocore error
```

Better:

```text
AWS authentication failed.

AIDeploy could not obtain valid AWS credentials.

Check:
1. `aws sts get-caller-identity`
2. AWS_PROFILE
3. your AWS CLI configuration
```

---

# 24. Security requirements

Follow least privilege as much as practical.

Do not request `AdministratorAccess` merely for convenience.

Document the IAM permissions required by AIDeploy.

Never:

* log credentials
* commit credentials
* store secrets in state
* put secrets into Docker image layers
* expose environment variables through status/log commands

---

# 25. README requirements

Write a high-quality README explaining:

1. What AIDeploy is
2. Why it exists
3. Architecture
4. Supported project type
5. AWS architecture
6. Installation
7. AWS setup
8. IAM permissions
9. Configuration
10. `init`
11. `up`
12. `status`
13. `logs`
14. `down`
15. Cost model
16. Limitations
17. Security considerations
18. Testing
19. Future roadmap

Be explicit:

> AIDeploy aims to minimize AWS costs but cannot guarantee zero cost. AWS pricing, free-tier eligibility, quotas, and usage limits can change.

---

# 26. Do NOT implement these in V1

Do not implement:

* web dashboard
* GitHub webhooks
* automatic GitHub deployments
* multiple deployment environments
* Kubernetes
* multi-region deployments
* custom domains
* sophisticated autoscaling
* AI agents
* AI log analysis
* automatic architecture decisions by LLM
* automatic database provisioning
* automatic DNS management

These belong in later versions.

---

# 27. Definition of Done

V1 is complete only when:

```text
✓ `aideploy init` works
✓ FastAPI project is detected
✓ configuration validates
✓ Docker image builds
✓ AWS deployment works
✓ public endpoint is returned
✓ /health succeeds
✓ status works
✓ logs work where supported
✓ down destroys AIDeploy-created resources
✓ resources are tagged
✓ secrets are never logged/stored
✓ cost policy is enforced
✓ failures are handled safely
✓ unit tests pass
✓ AWS integration tests are isolated
✓ linting passes
✓ type checking passes where configured
✓ README is complete
```

Before declaring completion, actually run the test suite and report:

```text
Tests:
X passed
Y skipped
Z failed

Lint:
PASS/FAIL

Type checking:
PASS/FAIL

AWS integration:
PASS/SKIPPED
```

Do not claim the implementation works if it has not been tested.

---

# 28. Implementation philosophy

Prefer:

```text
simple + explicit + deterministic
```

over:

```text
clever + abstract + over-engineered
```

The system is being built for personal use and portfolio projects first.

Every architectural decision should answer:

> Does this make deploying and destroying my FastAPI AI projects easier, safer, and cheaper?

If not, do not add it to V1.
