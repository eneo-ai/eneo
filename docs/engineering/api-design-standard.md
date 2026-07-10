# API design standard

Routers are HTTP adapters, not business logic owners.

## API consumer standard

An external developer should understand the API without reading backend source.
The API must make these journeys obvious:

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

## API maintainer standard

Every endpoint change must account for the applicable items below and mark
irrelevant ones not applicable:

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

Each request, response, and error shape has one canonical schema owner. Routers
attach HTTP metadata, obtain authorization decisions from the canonical policy
owner, and adapt application results without duplicating either contract.

Domain/application code must not raise FastAPI `HTTPException`. Translate domain
errors at the HTTP adapter boundary through a router or centralized exception
adapter.

## Contract review

For every API recommendation, include:

- canonical schema owner
- error contract
- permission check owner
- generated client impact
- backward compatibility/deletion path
- contract tests required
- reviewability impact
