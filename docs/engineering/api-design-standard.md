# API Design Standard

Routers are HTTP adapters, not business logic owners.

## API Consumer Standard

An external developer should understand the API without reading backend source. The API must make these journeys obvious:

- authenticate
- list resources
- inspect definitions
- understand required inputs
- upload or attach files
- start work
- poll status
- inspect step or partial output
- retrieve final result and artifacts
- pause, edit, resume, retry, and handle errors safely

## API Maintainer Standard

Every endpoint must have a clear owner for:

- path naming
- operation ID
- tags
- request model
- response model
- status codes
- pagination/filtering/sorting
- error shape
- authorization
- idempotency
- OpenAPI and generated client impact

Domain/application code must not raise FastAPI `HTTPException`. Translate domain errors at the router boundary.

## Contract Review

For every API recommendation, include:

- canonical schema owner
- error contract
- permission check owner
- generated client impact
- backward compatibility/deletion path
- contract tests required
- reviewability impact
