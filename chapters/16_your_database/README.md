# 16 — Query your own database

```bash
python chapters/16_your_database/run.py                       # the bundled sample
DATAAGENT_DB=/path/to/your.sqlite python chapters/16_your_database/run.py
```

Every chapter until now queried our NYC taxi warehouse — a schema the code already
knew by heart. This one points the agent at a database it has **never seen**: your
SQLite file. And that exposes the step every "chat with your database" product
depends on and rarely explains: before the model can write one correct query, it
has to be **taught the database**.

So the chapter does exactly that. It reads your schema out of the file, hands the
model the tables, columns, real values, and — crucially — the **relationships
between tables**, and only then runs text-to-SQL. Teaching the model the schema
and the ER structure *is* the chapter.

## What stays the same (almost everything)

The guardrail (`assert_safe`) and the result renderer (`QueryResult`) come straight
from the warehouse — they were always pure functions of the SQL string, never tied
to the taxi data. The agent loop is Chapter 05, unchanged, driven through the same
`execute` swap as Chapters 14–15. **Nothing in `dataagent/` changes.** The only new
code reads a schema out of SQLite and draws it.

It reads SQLite with the standard-library `sqlite3` module, not through DuckDB, for
one concrete reason found by testing: DuckDB's SQLite reader **drops foreign keys**,
and the foreign keys are precisely what the diagram and the model's JOINs need.

## Teaching the model: schema + relationships

`introspect()` walks the file with SQLite's own PRAGMAs and builds this context,
which goes into the system prompt:

```
CREATE TABLE customers (  -- 3 rows
  id INTEGER PRIMARY KEY,
  name TEXT,
  city TEXT
);
-- values: name in ('Alice', 'Bob', 'Carol'); city in ('Berlin', 'Hamburg')
...
Relationships (use these for JOINs):
- line_items.order_id → orders.id
- orders.customer_id → customers.id
```

The **relationships** block is the ER diagram's information rendered as text — the
form the model can actually act on. Give it to the model and it writes the JOIN
itself; withhold it and it guesses.

## The ER diagram (for you)

The same facts, drawn. `er_mermaid()` emits a Mermaid `erDiagram` — plain text, no
diagramming library — written to `sample_shop.mmd` and rendered here (GitHub, the
live demo, and Claude artifacts all render Mermaid natively):

```mermaid
erDiagram
  customers {
    INTEGER id PK
    TEXT name
    TEXT city
  }
  orders {
    INTEGER id PK
    INTEGER customer_id FK
    REAL total
    TEXT status
  }
  line_items {
    INTEGER id PK
    INTEGER order_id FK
    TEXT sku
    INTEGER qty
  }
  customers ||--o{ orders : "customer_id"
  orders ||--o{ line_items : "order_id"
```

Declared foreign keys are solid (`||--o{`). Databases that declare **no** foreign
keys — our taxi warehouse, most analytics schemas — would draw as boxes with no
edges, so the diagram falls back to **inferring** relationships from `<name>_id`
column names and marks them dashed (`||..o{`) and labelled *(inferred)*. A guess,
shown as a guess.

## A real run

```
read schema · 3 tables, 2 relationships
Q Which customer has the highest total order value? Give the name and the amount.
A Bob has the highest total order value, at 220.
answered from your DB · 1 tool calls · grounded=True · stop=answered
```

Bob's orders total 220 (120 + 80 + 20). The model got there by JOINing `customers`
to `orders` on the relationship we taught it — a table it learned about seconds
earlier. Writes never reach the file: `DELETE` is `REJECTED` by `assert_safe`, and
the connection is opened read-only besides. Both are checked in the tests.

## Your own data, *not* in SQLite

SQLite is the default because it needs nothing. To query a database that lives on
your own machine, the loop doesn't change — only where `execute` sends the SQL. Two
documented paths (not run in CI, since they need your database):

**Postgres, over MCP.** This reuses Chapter 15 exactly. Launch the maintained
Postgres MCP server and point the ch15 client at it:

```bash
export DATABASE_URI="postgresql://user:pass@localhost:5432/yourdb"
# the ch15 MCPClient launches this and drives its `query` tool:
#   uvx postgres-mcp --access-mode=restricted
```

The client is unchanged; the agent's `run_sql` is now the server's `query` tool, so
the SQL runs in Postgres. The schema and relationships come from one
`information_schema` query through that same tool (Postgres exposes foreign keys,
unlike the SQLite-through-DuckDB path) — feed the result to the same `er_mermaid()`
and the diagram is identical in shape.

**A CSV or Parquet file, no database at all.** DuckDB (already a dependency) reads
them directly — `SELECT * FROM read_csv_auto('sales.csv')` — so "your data" can be a
spreadsheet export. There are no foreign keys to draw, so the diagram uses the
inferred-relationship fallback above.

## Exercise

1. Point `DATAAGENT_DB` at any SQLite file you have and ask it a question. If the
   answer is wrong, read the schema context it built — usually a missing relationship
   or an unlisted enum value is why.
2. Add a `city_id` column to `orders` with no `REFERENCES` clause and rebuild. Watch
   it appear as a dashed, *(inferred)* edge — then decide whether the guess is right.
3. Wire up the Postgres path above against a real database and confirm the loop,
   the guardrail, and `er_mermaid()` are all reused untouched.

---

This is the payoff of every seam built so far: a read-only tool boundary, a schema
that fits the prompt, an agent loop that doesn't care what's behind the tool. Swap
the database and they all still hold.
