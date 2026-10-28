# Contributing to Eneo

Welcome to the Eneo community! This guide provides everything needed to contribute to the democratic AI platform for the public sector.

Anyone with a GitHub account can contribute: you do not need to belong to a team or an organisation. This file is the developer guide. Two companion pages on the documentation site follow the same steps:

- **[Contributing to Eneo](https://docs.eneo.ai/contributing)**: every way to contribute, how to create an issue, and the contribution steps with best practices.
- **[Governance and Roles](../frontend/apps/docs-site/src/content/contributing/governance.mdx)**: Core Maintainers and Collaborators, protected branches, releases, and an FAQ.

---

## 🌟 Our Mission

Eneo embodies the principle that **"Generative AI must not be a technology for the few, but a technology for everyone."** Contributors help build a platform that serves public sector organizations worldwide while maintaining democratic governance and open source principles.

---

## 🚀 Quick Start for Contributors

### 1. Start With an Issue

Every contribution starts with a GitHub issue, before any code is written. Search the [existing issues](https://github.com/eneo-ai/eneo/issues?q=is%3Aissue), open and closed, first. If nothing matches, choose a template under [**Issues → New issue**](https://github.com/eneo-ai/eneo/issues/new/choose):

- **Bug Report** for something that does not work as expected
- **Feature Request** for a new capability or an improvement
- **Finding** for a risk, problem or idea that is not yet a clear bug or feature

**Epic** and **Development task** are planning templates for scheduled roadmap work. Blank issues are turned off.

The project intake workflow labels each new issue from its template and Area, and adds it to the Eneo GitHub Project so maintainers can triage it. Comment that you would like to work on the issue and wait for a maintainer to confirm the approach: it avoids work that cannot be accepted, and your pull request must reference the issue.

> **Issues are public.** Do not include personal data, credentials, internal hostnames or user content. Report vulnerabilities privately, as described in [Vulnerability Reporting](#vulnerability-reporting).

### 2. Fork and Set Up the Development Environment

**Prerequisites:**
- Docker and VS Code with Dev Containers extension
- Git configured with your identity

**Setup Steps:**
```bash
# Fork on GitHub (https://github.com/eneo-ai/eneo/fork), then clone your fork
git clone https://github.com/YOUR_USERNAME/eneo.git
cd eneo

# Track the main repository so you can branch from its develop
git remote add upstream https://github.com/eneo-ai/eneo.git

# Open in VS Code
code .

# When prompted, click "Reopen in Container"
# Wait for devcontainer setup (2-3 minutes first time)

# Configure environment
cp backend/.env.template backend/.env
cp frontend/apps/web/.env.example frontend/apps/web/.env
# Edit .env files with your settings

# Initialize database
cd backend && uv run python init_db.py

# Start development servers (3 terminals)
cd backend && uv run start              # Terminal 1
cd frontend && bun run dev                 # Terminal 2
cd backend && uv run worker             # Terminal 3
```

**Optional: object storage locally**

Eneo stores file bytes in PostgreSQL by default, which is all most work needs.
To exercise the S3-compatible path instead, start the bundled SeaweedFS service
from the `object-content` Compose profile. It is off by default because the
image is built from upstream source, so the first start takes a few minutes.

```bash
docker compose -p eneo_devcontainer -f .devcontainer/docker-compose.yml \
  --profile object-content up -d object-content
```

To have VS Code bring it up together with the rest of the devcontainer, create
`.devcontainer/.env` (gitignored, so it stays a per-developer choice) with:

```
COMPOSE_PROFILES=object-content
```

Compose loads that file automatically because the devcontainer's project
directory is `.devcontainer/`. Rebuild or reopen the container to apply it.

Then connect it on the admin **File storage** page (`/admin/storage`). That page
is read-only unless one of your roles carries the **Storage** permission. Roles
that already have **Admin** were granted it automatically, and new tenants get
it from the predefined-role seed, so the tenant owner account you develop with
normally has it. If the page is read-only, add the Storage permission to your
role under **Admin > Roles**.

Use these values in the connection dialog. They match the Compose defaults; the
devcontainer already permits plain HTTP, generates a development
`ENCRYPTION_KEY`, and prints these values on start while the service runs:

| Field | Value |
| --- | --- |
| S3 endpoint | `http://object-content:8333` |
| Bucket | `eneo-object-content-dev` |
| Region for signing | `local` |
| Access key ID | `eneo-dev-object-content` |
| Secret access key | `local-development-only-secret` |
| Bucket addressing | `Bucket in the URL path` (the default) |

Leave `OBJECT_CONTENT_ENDPOINT_URL`, `OBJECT_CONTENT_REGION`,
`OBJECT_CONTENT_BUCKET`, `OBJECT_CONTENT_ACCESS_KEY_ID`,
`OBJECT_CONTENT_SECRET_ACCESS_KEY`, `OBJECT_CONTENT_DEPLOYMENT_ID`, and
`OBJECT_CONTENT_ADDRESSING_STYLE` unset. Setting any one of them switches Eneo
to the operator-managed connection instead, and the admin dialog stops being the
authority. See [docs/deployment/OBJECT_CONTENT.md](deployment/OBJECT_CONTENT.md)
for the operator-managed path and for connecting an external endpoint.

### 3. Branch From the Latest `develop`

```bash
# Start every branch from the main repository's develop
git fetch upstream
git switch -c feature/your-feature-name upstream/develop

# Install local hooks once per clone
pre-commit install --install-hooks --hook-type pre-commit --hook-type commit-msg --hook-type pre-push
```

Use a prefix that describes the work, as listed under [Branch Naming](#branch-strategy). The hooks run formatting, commit message and pre-push checks locally, so problems show up before CI.

### 4. Make and Test Your Change

```bash
# Run the tests for what you changed
(cd backend && uv run pytest)
(cd frontend && bun run test)

# Commit in small steps using Conventional Commits
git add <files>
git commit -m "feat(assistants): add system prompt validation"

# Push to your fork
git push -u origin feature/your-feature-name
```

Update tests and documentation in the same pull request when behaviour changes; see [Documentation Standards](#-documentation-standards). For a WIP push or a CI rerun where local hooks are not useful, use `git push --no-verify`. Do not use it to bypass a real failure before opening or merging a PR.

### 5. Open a Pull Request Against `develop`

Open a pull request from your fork into `eneo-ai/eneo`'s `develop` branch and fill in the [pull request template](../.github/pull_request_template.md):

- Write the title as a Conventional Commit, for example `fix(spaces): resolve permission check bug`. It becomes the commit message on `develop`.
- Link the issue under **Planning** with `Fixes #123`.
- Fill in **Changes**, **Why**, **User-facing** and **Testing**, plus **Accessibility** for UI changes.
- Leave **Allow edits by maintainers** ticked so a maintainer can push a small fix for you.
- Open it as a **draft** if you want early feedback on the direction.

### 6. Checks, Review and Merge

- `CI / CI`, `Dependency Review / Dependency Review` and `PR label policy / PR labels` must pass. For contributors outside the `eneo-ai` organisation, a maintainer approves the workflow runs before they start.
- If you cannot add labels yourself, a maintainer adds them during review and the PR label check turns green. A pull request that links no issue gets `needs:task-link` until you add `Fixes #123`.
- A member of `@eneo-ai/core-maintainers` reviews the pull request. Answer comments with new commits on the same branch rather than force-pushing, and resolve every conversation.
- When the change is ready, the Core Maintainer approves it and chooses **Merge when ready**. The pull request enters the merge queue as soon as the checks are green, and the queue tests it against the latest `develop` and squash-merges it. You only need to update your branch if GitHub reports a conflict.
- If you push new commits after that, GitHub cancels **Merge when ready** and a Core Maintainer looks at the change again.

Only Core Maintainers have write access and can add pull requests to the merge queue, so contributors always work from a fork. See [Governance and Roles](../frontend/apps/docs-site/src/content/contributing/governance.mdx).

**For Core Maintainers:** agree on the change as a team, then choose **Merge when ready** on your own pull request. It enters the merge queue when the checks are green; no formal approval from a colleague is required on `develop`, but ask for a written review when a change is large or risky. From the command line, `gh pr merge <number> --auto` works only while the repository setting **Allow auto-merge** is on; otherwise run `gh pr merge <number>` once the checks are green. There is no bypass, so nothing reaches `develop` without passing the checks. Pull requests into `release/*` and `main` need an approval from another Core Maintainer.

---

## 📏 Contribution Standards and Requirements

All contributions must align with Eneo's mission to provide democratic AI for the public sector. Review these requirements before submitting a PR.

### Generic Functionality Requirement

PRs must introduce generic functions useful for all platform users.

**Focus on:**
- Solving common problems across organizations
- Features that benefit the entire user base
- Improvements to core platform capabilities

**Avoid:**
- Municipality-specific features
- Company-specific integrations
- Custom workflows for individual organizations

### Design System Compliance

All UI contributions must follow Eneo's established design system.

**Requirements:**
- Use existing components and patterns
- Maintain consistent color scheme, typography, and spacing
- Follow the component library guidelines
- No custom styling that deviates from platform standards

> 📐 **Note**: A comprehensive design system in Figma is coming soon. Until then, follow existing UI patterns in the codebase and use the established component library.

### Platform Integrity

No PR may compromise existing functionality.

**Testing Requirements:**
- Include unit tests for new behavior
- Add integration tests for new features
- Test for regressions in related features
- Verify no breaking changes to existing APIs

### Examples of Acceptable vs Unacceptable Contributions

**✅ Good Contributions:**
- "Add support for Gemini AI models" - Benefits all users
- "Improve vector search performance" - Universal improvement
- "Add accessibility features for screen readers" - Platform-wide enhancement
- "Implement batch processing for documents" - General capability

**❌ Unacceptable Contributions:**
- "Add custom branding for Municipality X" - Too specific
- "Implement Company Y's approval workflow" - Organization-specific
- "Change color scheme to match our brand" - Violates design system
- "Add hard-coded integration with our internal system" - Not generic

### Submission Checklist

Before submitting your PR, ensure:
- [ ] Feature is generic and benefits all users
- [ ] UI follows existing design patterns
- [ ] All tests pass with adequate coverage
- [ ] No breaking changes introduced
- [ ] Documentation updated accordingly
- [ ] PR description clearly explains the universal benefit

---

## 🏗️ Understanding the Architecture

Eneo follows **Domain-Driven Design** with clear separation of concerns. Understanding this architecture is essential for effective contributions.

### Backend Domain Structure

<details>
<summary>📁 Click to view domain organization</summary>

```
backend/src/eneo/
├── assistants/           # AI Assistant Management
│   ├── api/             # FastAPI endpoints
│   ├── assistant.py     # Domain entity
│   ├── assistant_repo.py # Data access
│   ├── assistant_service.py # Business logic
│   └── assistant_factory.py # Object creation
├── spaces/              # Collaborative Workspaces
├── users/               # User Management
├── completion_models/   # AI Model Integration
├── sessions/            # Conversation Management
└── authentication/     # Security and Access Control
```

**Domain Pattern:**
Each domain follows a consistent 4-layer architecture:
1. **API Layer**: HTTP request/response handling
2. **Application Layer**: Business use cases
3. **Domain Layer**: Core business logic
4. **Infrastructure Layer**: Database and external services

</details>

### Frontend Architecture

```
frontend/
├── apps/web/            # Main SvelteKit application
│   ├── src/routes/      # File-based routing
│   ├── src/lib/         # Reusable components and utilities
│   └── src/app.html     # Root HTML template
├── packages/            # Shared packages
│   ├── eneo-js/       # Type-safe API client
│   └── ui/              # Reusable UI components
└── package.json         # Workspace configuration
```

---

## 💻 Development Standards

### Code Quality Requirements

**Python (Backend):**
- **Style**: PEP 8 compliance with Black formatting
- **Type Safety**: Full type hints for all functions
- **Documentation**: Docstrings for public APIs
- **Testing**: Unit tests with pytest

**TypeScript (Frontend):**
- **Style**: ESLint configuration with strict rules
- **Type Safety**: Strict TypeScript configuration
- **Components**: Svelte component best practices
- **Testing**: Vitest for unit tests, Playwright for E2E

### Domain-Driven Design Patterns

When adding new features, follow the established DDD patterns:

<details>
<summary>🏛️ Click to view DDD implementation example</summary>

**1. Create Domain Entity:**
```python
# assistants/assistant.py
@dataclass
class Assistant:
    id: UUID
    space_id: UUID
    name: str
    description: str
    system_prompt: str
    completion_model_id: UUID
    
    def update_system_prompt(self, prompt: str) -> None:
        """Update assistant's system prompt with validation."""
        if not prompt.strip():
            raise ValueError("System prompt cannot be empty")
        self.system_prompt = prompt.strip()
```

**2. Define Repository Interface:**
```python
# assistants/assistant_repo.py
class AssistantRepository(Protocol):
    async def find_by_id(self, id: UUID) -> Optional[Assistant]:
        """Find assistant by ID."""
        ...
    
    async def save(self, assistant: Assistant) -> None:
        """Save assistant to storage."""
        ...
```

**3. Implement Service Layer:**
```python
# assistants/assistant_service.py
class AssistantService:
    def __init__(self, repo: AssistantRepository):
        self._repo = repo
    
    async def create_assistant(self, request: CreateAssistantRequest) -> Assistant:
        """Create new assistant with validation."""
        assistant = Assistant(
            id=uuid4(),
            space_id=request.space_id,
            name=request.name,
            description=request.description,
            system_prompt=request.system_prompt,
            completion_model_id=request.completion_model_id
        )
        await self._repo.save(assistant)
        return assistant
```

**4. Create API Layer:**
```python
# assistants/api/assistant_router.py
@router.post("/assistants", response_model=AssistantResponse)
async def create_assistant(
    request: CreateAssistantRequest,
    service: AssistantService = Depends()
) -> AssistantResponse:
    """Create a new AI assistant."""
    assistant = await service.create_assistant(request)
    return AssistantResponse.from_domain(assistant)
```

</details>

---

## 🧪 Testing Guidelines

### Backend Testing

**Test Structure:**
```
tests/
├── unittests/           # Domain-organized unit tests
│   ├── assistants/
│   │   ├── test_assistant.py
│   │   ├── test_assistant_service.py
│   │   └── test_assistant_factory.py
│   └── conftest.py      # Shared test fixtures
└── fixtures.py          # Test data factories
```

**Testing Patterns:**
```python
# Test domain entity
def test_assistant_update_system_prompt():
    assistant = AssistantFactory.create()
    new_prompt = "You are a helpful assistant."
    
    assistant.update_system_prompt(new_prompt)
    
    assert assistant.system_prompt == new_prompt

# Test service layer
async def test_create_assistant():
    repo = MockAssistantRepository()
    service = AssistantService(repo)
    request = CreateAssistantRequest(
        space_id=uuid4(),
        name="Test Assistant",
        description="Test description",
        system_prompt="Test prompt",
        completion_model_id=uuid4()
    )
    
    assistant = await service.create_assistant(request)
    
    assert assistant.name == "Test Assistant"
    assert repo.saved_assistant == assistant
```

**Run Tests:**
```bash
cd backend

# Run all tests
uv run pytest

# Run specific domain tests
uv run pytest tests/unittests/assistants/

# Run specific test
uv run pytest tests/unittests/assistants/test_assistant.py::test_assistant_update_system_prompt
```

### Frontend Testing

**Component Testing:**
```typescript
// tests/components/AssistantCard.test.ts
import { render, screen } from '@testing-library/svelte';
import AssistantCard from '$lib/components/AssistantCard.svelte';

test('displays assistant information', () => {
    const assistant = {
        id: '123',
        name: 'Test Assistant',
        description: 'Test description'
    };
    
    render(AssistantCard, { props: { assistant } });
    
    expect(screen.getByText('Test Assistant')).toBeInTheDocument();
    expect(screen.getByText('Test description')).toBeInTheDocument();
});
```

**Run Frontend Tests:**
```bash
cd frontend

# Unit tests
bun run test

# E2E tests
bun run test:integration

# Type checking
bun run check

# Linting
bun run lint
```

---

## 🔄 Development Workflow

### Branch Strategy

```mermaid
gitgraph
    commit id: "develop"
    branch feature/new-assistant-type
    checkout feature/new-assistant-type
    commit id: "feat: add domain entity"
    commit id: "feat: add service layer"
    commit id: "feat: add API endpoints"
    commit id: "test: add comprehensive tests"
    checkout develop
    merge feature/new-assistant-type
    commit id: "merge: new assistant type"
```

> Features always flow back to `develop`. Version tags live on `release/vX.Y` branches (for example `release/v2.0` and `release/v2.1`), not on `develop`. See [DEPLOYMENT_WORKFLOW.md](./DEPLOYMENT_WORKFLOW.md) for the full release flow.

**Branch Naming:**
- `feature/description` - New features
- `fix/description` - Bug fixes
- `docs/description` - Documentation updates
- `refactor/description` - Code refactoring
- `test/description` - Test improvements

### Commit Message Format

Follow [Conventional Commits](https://www.conventionalcommits.org/):

```
type(scope): description

[optional body]

[optional footer]
```

**Examples:**
```bash
feat(assistants): add system prompt validation
fix(spaces): resolve permission check bug
docs(api): update assistant endpoint documentation
test(users): add integration tests for user creation
```

### Pull Request Process

The step-by-step flow is in [Quick Start for Contributors](#-quick-start-for-contributors). These rules apply to every pull request:

1. **Create Focused PRs**: One issue, one pull request. Split unrelated changes.
2. **Use a Conventional Commit Title**: The title becomes the squash commit message on `develop`.
3. **Link the Issue**: Write `Fixes #123` under **Planning** in the template.
4. **Write Clear Descriptions**: Explain what changes and why.
5. **Include Tests**: All new functionality requires tests.
6. **Update Documentation**: Keep docs synchronized with code changes.
7. **Describe the User-facing Change**: Fill in the `## User-facing` section of the PR template (one or two sentences from the user's point of view, or `No`) and give anything worth pointing at a `data-tour="…"` anchor. Release notes are drafted from these sections — see [`frontend/packages/whats-new/PLAYBOOK.md`](../frontend/packages/whats-new/PLAYBOOK.md).
8. **Labels**: Every PR needs one change type and at least one area, as described in the [required-label policy](../.github/PROJECT_WORKFLOW.md#required-labels). If you cannot add labels, a maintainer adds them.
9. **Review**: GitHub requests a review from `@eneo-ai/core-maintainers` automatically through `.github/CODEOWNERS`. A Core Maintainer approves contributions from outside the team, and only Core Maintainers can add a pull request to the merge queue. See [Governance and Roles](../frontend/apps/docs-site/src/content/contributing/governance.mdx).

**PR Template:** GitHub fills in the [pull request template](../.github/pull_request_template.md) when you open a PR. Its sections are **Changes**, **Why**, **Planning**, **User-facing**, **Testing**, **Accessibility** (for UI changes) and **Screenshots**.

---

## 🗄️ Database Changes

### Migration Guidelines

**Creating Migrations:**
```bash
cd backend

# Generate migration for model changes
uv run alembic revision --autogenerate -m "add assistant categories"

# Review generated migration file
# Edit if necessary for data migrations or complex changes

# Apply migration locally
uv run alembic upgrade head

# Test rollback
uv run alembic downgrade -1
uv run alembic upgrade head
```

**Migration Best Practices:**
- Always review auto-generated migrations
- Include data migrations when schema changes affect existing data
- Test both upgrade and downgrade paths
- Use descriptive migration messages
- Never edit applied migrations; create new ones

**Example Migration:**
```python
# alembic/versions/add_assistant_categories.py
def upgrade() -> None:
    # Add new column
    op.add_column('assistants', sa.Column('category', sa.String(50), nullable=True))
    
    # Populate existing records with default value
    op.execute("UPDATE assistants SET category = 'general' WHERE category IS NULL")
    
    # Make column non-nullable
    op.alter_column('assistants', 'category', nullable=False)

def downgrade() -> None:
    op.drop_column('assistants', 'category')
```

---

## 🌍 Internationalization

Eneo supports Swedish and English. When adding new features:

**Adding New Text:**
```typescript
// frontend/apps/web/src/lib/paraglide/messages.js

// Add new message keys
export const messages = {
    en: {
        assistants: {
            create_button: "Create Assistant",
            delete_confirm: "Are you sure you want to delete this assistant?"
        }
    },
    sv: {
        assistants: {
            create_button: "Skapa Assistent", 
            delete_confirm: "Är du säker på att du vill ta bort denna assistent?"
        }
    }
};

// Use in components
import * as m from '$lib/paraglide/messages.js';

<button>{m.assistants_create_button()}</button>
```

**Translation Guidelines:**
- All user-facing text must be translatable
- Use descriptive message keys
- Provide context for translators in comments
- Test both language versions
- Swedish should feel natural, not translated

---

## 🔐 Security Guidelines

### Security Requirements

**Data Protection:**
- Never log or expose sensitive data (API keys, passwords, PII)
- Validate all input at API boundaries
- Use parameterized queries to prevent SQL injection
- Implement proper access controls for all endpoints

**Authentication & Authorization:**

Every HTTP and WebSocket endpoint must declare who it accepts and who may call it with `@endpoint_access`, directly below the route decorator. The application refuses to start if a route is missing a declaration. Domain services still check space membership, tenant boundaries and ownership.

```python
@router.post("/{provider_id}/test/")
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Permission.ADMIN,
    reason="Uses organization-managed provider credentials.",
)
async def test_provider(provider_id: UUID, user: CurrentUser):
    ...
```

See *Declare access on every endpoint* in [Security for Contributors](../frontend/apps/docs-site/src/content/contributing/security.mdx) for the rules and the tests to add.

### Vulnerability Reporting

**Security Issues:**
- Report security vulnerabilities privately, through [**Security → Report a vulnerability**](https://github.com/eneo-ai/eneo/security/advisories/new) on GitHub or by email to security@sundsvall.se. Never use a public issue, pull request or discussion.
- Include detailed reproduction steps
- Allow reasonable time for fix before public disclosure
- Security fixes receive priority handling

See [SECURITY.md](SECURITY.md) for what to include and the response targets.

---

## 📦 Dependencies

### Adding Dependencies

**Backend Dependencies:**
```bash
cd backend

# Add runtime dependency
uv add package-name

# Add development dependency  
uv add --group dev package-name

# Update pyproject.toml with specific version constraints
# Commit both pyproject.toml and uv.lock
```

**Frontend Dependencies:**
```bash
cd frontend

# Add dependency to specific package
bun add package-name --filter web

# Add shared dependency to workspace root
bun add package-name -w

# Add development dependency
bun add -d package-name
```

**Dependency Guidelines:**
- Justify new dependencies in PR description
- Prefer well-maintained packages with active communities
- Consider bundle size impact for frontend dependencies
- Pin major versions to avoid breaking changes
- Regularly audit and update dependencies

---

## 📚 Documentation Standards

For product documentation and release notes, start with the
[documentation authoring guide](../frontend/apps/docs-site/AUTHORING.md).
It owns branch selection, page placement and the distinction between detailed
guides and user-facing release announcements.

### Code Documentation

**Python Docstrings:**
```python
async def create_assistant(
    self, 
    request: CreateAssistantRequest,
    user: User
) -> Assistant:
    """Create a new AI assistant.
    
    Args:
        request: Assistant creation parameters including name, description,
                and configuration settings.
        user: The user creating the assistant, used for authorization.
    
    Returns:
        The created assistant instance with generated ID.
    
    Raises:
        ValidationError: If request parameters are invalid.
        AuthorizationError: If user lacks permission to create assistants.
        
    Example:
        >>> request = CreateAssistantRequest(name="Helper", ...)
        >>> assistant = await service.create_assistant(request, user)
        >>> assert assistant.name == "Helper"
    """
```

**TypeScript Documentation:**
```typescript
/**
 * Creates a new assistant with the provided configuration.
 * 
 * @param data - Assistant creation parameters
 * @returns Promise resolving to the created assistant
 * @throws {ValidationError} When data is invalid
 * @throws {AuthorizationError} When user lacks permissions
 * 
 * @example
 * ```typescript
 * const assistant = await createAssistant({
 *   name: "Helper",
 *   description: "A helpful assistant"
 * });
 * ```
 */
async function createAssistant(data: CreateAssistantData): Promise<Assistant> {
    // Implementation...
}
```

### API Documentation

All API endpoints automatically generate OpenAPI documentation. Ensure:
- Clear endpoint descriptions
- Comprehensive request/response models
- Example requests and responses
- Error status codes and descriptions

---

## 🎯 Contribution Areas

### High-Priority Areas

**1. AI Model Integration:**
- Add support for new AI providers
- Improve model switching and fallback logic
- Optimize token usage and cost management

**2. User Experience:**
- Enhance accessibility features
- Improve mobile responsiveness  
- Streamline onboarding workflows

**3. Performance:**
- Optimize database queries
- Improve vector search performance
- Enhance caching strategies

**4. Security & Compliance:**
- Strengthen authentication mechanisms
- Improve audit logging
- Enhance GDPR compliance features
- Multi-tenant security enhancements

**5. Multi-Tenancy & Enterprise Features:**
- Per-tenant resource quotas and limits
- Federation provider integrations (new IdPs)
- Credential management improvements
- Observability and debugging tools

**6. Knowledge Management:**
- Website crawler enhancements (pagination, JavaScript rendering)
- HTTP authentication for protected resources
- Document processing improvements
- Semantic search optimization

### Good First Issues

New contributors should look for issues labeled [`good first issue`](https://github.com/eneo-ai/eneo/labels/good%20first%20issue) or [`help wanted`](https://github.com/eneo-ai/eneo/labels/help%20wanted):
- Documentation improvements
- UI component enhancements
- Test coverage improvements
- Bug fixes with clear reproduction steps

---

## 🏢 Community Guidelines

### Code of Conduct

Eneo follows the [Contributor Covenant Code of Conduct](https://www.contributor-covenant.org/). All contributors are expected to:

- Use welcoming and inclusive language
- Respect differing viewpoints and experiences
- Accept constructive criticism gracefully
- Focus on what is best for the community
- Show empathy towards other community members

### Communication Channels

**Development Discussion:**
- GitHub Issues for bugs and feature requests
- GitHub Discussions for general questions
- Pull Request comments for code review

**Community Support:**
- GitHub Discussions for community questions, open to everyone
- [Forum](https://forum.eneo.ai) and [chat](https://chat.eneo.ai) for public-sector employees (both require a public-sector email address)
- Email: digitalisering@sundsvall.se for organizations that want to join the collaboration; see [Samarbetsforum](https://eneo.ai/samarbetsforum.html) for how Eneo is governed

### Recognition

Contributors are recognized through:
- Contribution credits in release notes
- GitHub contributor statistics
- Special recognition for significant contributions
- Invitation to contributor meetings (for active contributors)

---

## 🚢 Release Process

### Version Numbering

Eneo follows [Semantic Versioning](https://semver.org/):
- **MAJOR**: Breaking changes
- **MINOR**: New features, backward compatible
- **PATCH**: Bug fixes, backward compatible

### Contributing to Releases

- Feature freeze 1 week before minor releases
- Critical bug fixes accepted during freeze
- Core Maintainers decide what enters the merge queue, cut release branches and publish releases
- Changelog updated with each release

---

## 🤝 Getting Help

### For New Contributors

**Getting Started:**
1. Join the [GitHub Discussions](https://github.com/eneo-ai/eneo/discussions)
2. Look for `good first issue` and `help wanted` labels
3. Read through existing code to understand patterns
4. Ask questions in discussions or issue comments

**Mentorship:**
- Experienced contributors provide guidance on complex features
- Code review feedback helps learn best practices
- Pair programming sessions available for significant contributions

### For Experienced Contributors

**Advanced Topics:**
- Architecture decision discussions
- Performance optimization strategies
- Security review processes
- Integration with public sector requirements

---

## 📈 Success Metrics

### Contribution Quality

**Code Quality Metrics:**
- No critical security vulnerabilities
- Performance regression prevention
- Documentation completeness

**Community Health:**
- Responsive code review (within 48 hours)
- Constructive feedback culture
- Knowledge sharing through documentation
- Inclusive contribution environment

---

Thank you for contributing to Eneo! Your work helps make AI technology democratic and accessible to public sector organizations worldwide. Together, we're building a platform that truly serves the public interest.

**Questions?** Join our [GitHub Discussions](https://github.com/eneo-ai/eneo/discussions) or reach out to digitalisering@sundsvall.se
