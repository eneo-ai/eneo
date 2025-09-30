# Claude Code Context: Eneo Crawler Project

## Project Overview

This is a web application with **backend** (Python/FastAPI) and **frontend** (TypeScript/React) that provides AI-powered website crawling and knowledge extraction capabilities.

## Current Architecture

### Backend (`backend/`)
- **Language**: Python 3.11+
- **Framework**: FastAPI with async/await
- **Database**: PostgreSQL with SQLAlchemy ORM
- **Crawler**: Scrapy with crochet for async integration
- **Task Queue**: Background job processing
- **Testing**: pytest

### Frontend (`frontend/`)
- **Language**: TypeScript
- **Framework**: React with modern hooks
- **Build**: Turborepo monorepo structure
- **Structure**: `apps/web/` (main app) + `packages/` (shared components)

## Recent Changes (Feature 001-add-crawl4ai-as)

### New Crawler Engine Support
**Status**: ✅ COMPLETED - Full implementation with crawler engine abstraction

Added support for **crawl4ai** as an alternative crawler engine alongside existing Scrapy implementation:

#### Key Components Added/Modified
1. **CrawlerEngine Enum**: `backend/src/intric/websites/domain/crawler_engine.py`
   - Values: `SCRAPY` (default), `CRAWL4AI`

2. **Website Models Enhanced**: `backend/src/intric/websites/presentation/website_models.py`
   - Added `crawler_engine` field to `WebsiteCreate`, `WebsiteUpdate`, `WebsitePublic`
   - Backwards compatible with default to `SCRAPY`

3. **API Endpoints Modified**:
   - `POST /spaces/{id}/knowledge/websites/` - website creation with engine selection
   - `POST /websites/{id}/` - website update with engine modification

4. **Database Schema**: Added `crawler_engine` column to `websites` table
   - Migration preserves existing data with `SCRAPY` default

#### Engine Abstraction (✅ IMPLEMENTED)
```
backend/src/intric/crawler/engines/
├── __init__.py          # Engine factory with get_engine() function
├── base.py              # CrawlerEngineAbstraction interface
├── scrapy_engine.py     # Existing Scrapy wrapped as engine
└── crawl4ai_engine.py   # New crawl4ai implementation with AsyncWebCrawler
```

### Implementation Approach
- **Backwards Compatible**: All existing code continues working unchanged
- **Default Behavior**: New websites default to Scrapy unless specified
- **Engine Selection**: Per-website configuration via `crawler_engine` parameter
- **Identical Output**: Both engines produce same `CrawledPage` format

## File Structure

### Core Crawler System
```
backend/src/intric/crawler/
├── crawler.py           # Main Crawler class (orchestrator)
├── parse_html.py        # CrawledPage model + HTML processing
├── spiders/            # Scrapy spider implementations
│   ├── crawl_spider.py
│   └── sitemap_spider.py
└── engines/            # NEW: Engine abstraction layer
    ├── base.py         # Abstract CrawlerEngine interface
    ├── scrapy_engine.py
    └── crawl4ai_engine.py
```

### Website Management
```
backend/src/intric/websites/
├── domain/
│   ├── website.py       # Website domain model (modified)
│   └── crawler_engine.py # NEW: CrawlerEngine enum
├── presentation/
│   └── website_models.py # API models (modified)
└── application/
    └── website_crud_service.py # Service layer (modified)
```

### API Layer
```
backend/src/intric/
├── spaces/api/
│   └── space_router.py  # Website creation endpoint (modified)
└── websites/presentation/
    └── website_router.py # Website update endpoint (modified)
```

## Key Data Models

### CrawledPage (Core Output)
```python
@dataclass
class CrawledPage:
    url: str
    title: str
    content: str  # Markdown-formatted content
```

### Website (Domain Model)
```python
class Website:
    # Existing fields
    url: str
    name: Optional[str]
    download_files: bool
    crawl_type: CrawlType  # CRAWL or SITEMAP
    update_interval: UpdateInterval

    # NEW field
    crawler_engine: CrawlerEngine  # SCRAPY or CRAWL4AI
```

## Configuration Patterns

### Environment Variables
- `SETTINGS.crawl_max_length`: 4 hour timeout
- `SETTINGS.closespider_itemcount`: 20,000 pages max
- `SETTINGS.obey_robots`: Respect robots.txt
- `SETTINGS.autothrottle_enabled`: Rate limiting

### Database Connection
- PostgreSQL with async SQLAlchemy
- Alembic for migrations
- Enum types for `CrawlType`, `UpdateInterval`, `CrawlerEngine`

## Testing Approach

### Implementation Status
- ✅ All 26 tasks completed across 8 phases
- ✅ Engine abstraction layer implemented
- ✅ API endpoints updated with crawler_engine parameter
- ✅ Database migration ready for deployment
- ✅ Full backwards compatibility maintained

### Contract Tests
- `specs/001-add-crawl4ai-as/contracts/test_website_creation_contract.py`
- `specs/001-add-crawl4ai-as/contracts/test_website_update_contract.py`
- Ready for testing with implemented API changes

### Test Structure
```
backend/tests/
├── integration/    # API endpoint tests
├── unit/          # Component unit tests
└── contract/      # API contract validation
```

## Common Tasks

### Adding New API Endpoints
1. Define Pydantic models in `presentation/models.py`
2. Add router endpoint with proper dependencies
3. Implement service layer logic
4. Add domain model updates if needed
5. Create contract tests first (TDD approach)

### Database Migrations
1. Create migration in `backend/alembic/versions/`
2. Use enum types for structured data
3. Always provide backwards-compatible defaults
4. Test migration with existing data

### Crawler Extensions
1. Implement `CrawlerEngine` abstract interface
2. Map to consistent `CrawledPage` output format
3. Handle configuration and error cases
4. Maintain async patterns throughout

## Development Commands

### Backend
```bash
cd backend
# Install dependencies
pip install -r requirements.txt

# Run tests
pytest

# Database migration
alembic upgrade head

# Start development server
uvicorn intric.main:app --reload
```

### Frontend
```bash
cd frontend
# Install dependencies
npm install

# Start development
npm run dev

# Build
npm run build
```

## Architecture Principles

### Constitution Compliance
- **KISS**: Simple implementations first, complexity requires justification
- **OpenAPI-First**: All API changes update OpenAPI specs
- **Progressive Development**: Backwards compatible changes
- **Human-Readable Code**: Clear intent, meaningful names

### Error Handling
- Structured exceptions with clear error messages
- Graceful degradation for non-critical failures
- Comprehensive logging for debugging
- User-friendly error responses

### Performance Considerations
- Async/await throughout Python backend
- Streaming results for large crawl operations
- Resource limits and timeouts
- Efficient database queries with proper indexing

## Engine Usage Guide

### Creating Websites with Specific Engines

```python
# API Request - Create with Scrapy (default)
{
    "name": "Traditional Site",
    "url": "https://example.com",
    "crawler_engine": "scrapy"  # Optional, defaults to scrapy
}

# API Request - Create with crawl4ai
{
    "name": "Modern SPA",
    "url": "https://spa-app.com",
    "crawler_engine": "crawl4ai"  # For JavaScript-heavy sites
}
```

### Engine Selection Logic
```python
from intric.crawler.engines import get_engine
from intric.websites.domain.crawler_engine import CrawlerEngine

# Get appropriate engine implementation
engine = get_engine(CrawlerEngine.CRAWL4AI)
async for page in engine.crawl(url="https://example.com"):
    process_page(page)
```

### Migration Strategy
1. **Existing websites**: Automatically use Scrapy (no changes needed)
2. **New websites**: Choose engine via `crawler_engine` parameter
3. **Gradual rollout**: Test crawl4ai on specific websites first
4. **Performance comparison**: Monitor crawl results between engines

## Recent Architectural Decisions

1. **Engine Abstraction**: ✅ Implemented clean interface for multiple crawler backends
2. **Backwards Compatibility**: ✅ Preserved all existing API contracts
3. **Default Engine**: ✅ Scrapy remains default to ensure zero-downtime migration
4. **Per-Website Configuration**: ✅ Engine selection at website level, not global
5. **Identical Output Format**: ✅ Both engines produce same CrawledPage structures

When implementing new features:
- Follow existing patterns in the codebase
- Maintain backwards compatibility
- Add comprehensive tests
- Update API documentation
- Consider performance and resource implications
