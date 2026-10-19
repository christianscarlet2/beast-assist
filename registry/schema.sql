-- Skills Registry: one row per skill (latest version) plus an append-only history.
CREATE TABLE IF NOT EXISTS skills (
  name          text PRIMARY KEY,
  version       text        NOT NULL,
  lifecycle     text        NOT NULL CHECK (lifecycle IN ('draft', 'beta', 'production', 'deprecated')),
  description   text        NOT NULL,
  owner         text        NOT NULL,
  tags          jsonb       NOT NULL DEFAULT '[]',
  aliases       jsonb       NOT NULL DEFAULT '[]',
  allowed_tools jsonb       NOT NULL,
  preflight     jsonb       NOT NULL DEFAULT '[]',
  body          text        NOT NULL,
  sha256        text        NOT NULL,
  published_by  text        NOT NULL,
  updated_at    timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS skill_versions (
  id           bigserial PRIMARY KEY,
  name         text        NOT NULL,
  version      text        NOT NULL,
  sha256       text        NOT NULL,
  doc          jsonb       NOT NULL,
  published_by text        NOT NULL,
  published_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (name, version)
);
CREATE INDEX IF NOT EXISTS skills_tags ON skills USING gin (tags);
