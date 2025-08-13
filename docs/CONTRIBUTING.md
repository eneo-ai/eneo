# Contributing to Eneo

Welcome to the Eneo community! This guide provides everything needed to contribute to the democratic AI platform for the public sector.

---

## 🌟 Our Mission

Eneo embodies the principle that **"Generative AI must not be a technology for the few, but a technology for everyone."** Contributors help build a platform that serves public sector organizations worldwide while maintaining democratic governance and open source principles.

---

## 🚀 Quick Start for Contributors

### 1. Development Environment Setup

**Prerequisites:**
- Docker and VS Code with Dev Containers extension
- Git configured with your identity

**Setup Steps:**
```bash
# Fork and clone the repository
git clone https://github.com/YOUR_USERNAME/eneo.git
cd eneo

# Open in VS Code
code .

# When prompted, click "Reopen in Container"
# Wait for devcontainer setup (2-3 minutes first time)

# Configure environment
cp backend/.env.template backend/.env
cp frontend/apps/web/.env.example frontend/apps/web/.env
# Edit .env files with your settings

# Initialize database
cd backend && poetry run python init_db.py

# Start development servers (3 terminals)
cd backend && poetry run start              # Terminal 1
cd frontend && pnpm run dev                 # Terminal 2  
cd backend && poetry run arq src.intric.worker.arq.WorkerSettings  # Terminal 3
```

### 2. Make Your First Contribution

```bash
# Create feature branch
git checkout -b feature/your-feature-name

# Make changes and test
# ... your development work ...

# Run tests
cd backend && poetry run pytest
cd frontend && pnpm run test

# Commit changes
git add .
git commit -m "feat: add your feature description"

# Push and create pull request
git push origin feature/your-feature-name
```

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
- Include comprehensive unit tests (≥80% coverage)
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
backend/src/intric/
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
│   ├── intric-js/       # Type-safe API client
│   └── ui/              # Reusable UI components
└── pnpm-workspace.yaml  # Monorepo configuration
```

---

## 💻 Development Standards

### Code Quality Requirements

**Python (Backend):**
- **Style**: PEP 8 compliance with Black formatting
- **Type Safety**: Full type hints for all functions
- **Documentation**: Docstrings for public APIs
- **Testing**: Unit tests with pytest, ≥80% coverage target

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
poetry run pytest

# Run specific domain tests
poetry run pytest tests/unittests/assistants/

# Run with coverage
poetry run pytest --cov=src --cov-report=html

# Run specific test
poetry run pytest tests/unittests/assistants/test_assistant.py::test_assistant_update_system_prompt
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
pnpm run test

# E2E tests
pnpm run test:integration

# Type checking
pnpm run check

# Linting
pnpm run lint
```

---

## 🔄 Development Workflow

### Branch Strategy

```mermaid
gitgraph
    commit id: "main"
    branch feature/new-assistant-type
    checkout feature/new-assistant-type
    commit id: "feat: add domain entity"
    commit id: "feat: add service layer"
    commit id: "feat: add API endpoints"
    commit id: "test: add comprehensive tests"
    checkout main
    merge feature/new-assistant-type
    commit id: "merge: new assistant type"
```

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

1. **Create Focused PRs**: One feature or fix per pull request
2. **Write Clear Descriptions**: Explain what changes and why
3. **Include Tests**: All new functionality requires tests
4. **Update Documentation**: Keep docs synchronized with code changes
5. **Request Review**: At least one approval required from maintainers

**PR Template:**
```markdown
## Description
Brief description of changes and motivation.

## Type of Change
- [ ] Bug fix (non-breaking change fixing an issue)
- [ ] New feature (non-breaking change adding functionality)
- [ ] Breaking change (fix or feature causing existing functionality to change)
- [ ] Documentation update

## Testing
- [ ] Unit tests pass
- [ ] Integration tests pass
- [ ] Manual testing completed

## Checklist
- [ ] Code follows project style guidelines
- [ ] Self-review completed
- [ ] Documentation updated
- [ ] No breaking changes without major version bump
```

---

## 🗄️ Database Changes

### Migration Guidelines

**Creating Migrations:**
```bash
cd backend

# Generate migration for model changes
poetry run alembic revision --autogenerate -m "add assistant categories"

# Review generated migration file
# Edit if necessary for data migrations or complex changes

# Apply migration locally
poetry run alembic upgrade head

# Test rollback
poetry run alembic downgrade -1
poetry run alembic upgrade head
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
```python
# Secure endpoint example
@router.get("/assistants/{assistant_id}")
async def get_assistant(
    assistant_id: UUID,
    current_user: User = Depends(get_current_user),
    service: AssistantService = Depends()
) -> AssistantResponse:
    """Get assistant with proper authorization."""
    # Verify user has access to the assistant's space
    assistant = await service.get_assistant_with_auth_check(
        assistant_id, 
        current_user
    )
    return AssistantResponse.from_domain(assistant)
```

### Vulnerability Reporting

**Security Issues:**
- Report security vulnerabilities privately to: security@sundsvall.se
- Include detailed reproduction steps
- Allow reasonable time for fix before public disclosure
- Security fixes receive priority handling

---

## 📦 Dependencies

### Adding Dependencies

**Backend Dependencies:**
```bash
cd backend

# Add runtime dependency
poetry add package-name

# Add development dependency  
poetry add --group dev package-name

# Update pyproject.toml with specific version constraints
# Commit both pyproject.toml and poetry.lock
```

**Frontend Dependencies:**
```bash
cd frontend

# Add dependency to specific package
pnpm add package-name --filter=web

# Add shared dependency to workspace root
pnpm add package-name -w

# Add development dependency
pnpm add -D package-name
```

**Dependency Guidelines:**
- Justify new dependencies in PR description
- Prefer well-maintained packages with active communities
- Consider bundle size impact for frontend dependencies
- Pin major versions to avoid breaking changes
- Regularly audit and update dependencies

---

## 📚 Documentation Standards

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

### Good First Issues

New contributors should look for issues labeled `good-first-issue`:
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
- Email: digitalisering@sundsvall.se (public sector organizations)
- GitHub Discussions for community questions

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

### Release Schedule

- **Minor releases**: Monthly (feature additions)
- **Patch releases**: As needed (critical bug fixes)
- **Major releases**: Quarterly (breaking changes)

### Contributing to Releases

- Feature freeze 1 week before minor releases
- Critical bug fixes accepted during freeze
- All changes require approval from maintainers
- Changelog updated with each release

---

## 🤝 Getting Help

### For New Contributors

**Getting Started:**
1. Join the [GitHub Discussions](https://github.com/eneo-ai/eneo/discussions)
2. Look for `good-first-issue` labels
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
- Test coverage maintained above 80%
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