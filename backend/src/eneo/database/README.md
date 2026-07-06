# Database operation with Alembic

Alembic handles manipulation of our PSQL database using SQLAlchemy as an engine

Tutorial for reference: https://www.jeffastor.com/blog/pairing-a-postgresql-db-with-your-dockerized-fastapi-app


## How to make migrations
Migrations are changes that will be applied to the database

Make a migration:

`alembic revision -m "create main tables"`

Which will create a file inside the migrations/versions folder

We can edit that file and make the modifications to the database as we wish, using SQLAlchemy commands

An example would be to add a table like this: 

```
def create_questionss_table() -> None:
    op.create_table(
        "questions",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("text", sa.Text, nullable=False, index=True),
        sa.Column("session", sa.Text, nullable=True),
    )
def upgrade() -> None:
    create_questionss_table()
def downgrade() -> None:
    op.drop_table("questions")
```

In order to apply it to the database, use

`alembic upgrade head`

which applies the migration

You can now connect to postgres and check if it worked using PSQL or PGAdmin.
`psql -h localhost -U postgres --dbname=postgres`


You can also downgrade using 

`alembic downgrade base` where base is the initial state

You can also use Relative Migration Identifiers, +2, -1 etc. See more here: https://alembic.sqlalchemy.org/en/latest/tutorial.html


