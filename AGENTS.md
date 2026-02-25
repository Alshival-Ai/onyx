# PROJECT KNOWLEDGE BASE

This file provides guidance to AI agents when working with code in this repository.

## KEY NOTES

- If you run into any missing python dependency errors, try running your command with `source .venv/bin/activate` \
  to assume the python venv.
- To make tests work, check the `.env` file at the root of the project to find an OpenAI key.
- If using `playwright` to explore the frontend, start the web service with:
  `./tools/bake.sh web --compose-up --compose-file docker-compose.dev.yml --compose-up-service web_server`.
  You can usually log in with username `a@example.com` and password `a`. The app can be accessed at
  `https://dev.starwoodgpt.prosourceit.app/`.
- You should assume that all Onyx services are running. To verify, you can check the `backend/log` directory to
  make sure we see logs coming out from the relevant service.
- To connect to the Postgres database, use: `docker exec -it onyx-relational_db-1 psql -U postgres -c "<SQL>"`
- When making calls to the backend, always go through the frontend. E.g. make a call to
  `https://dev.starwoodgpt.prosourceit.app/api/persona` not `http://localhost:8080/api/persona`
- Put ALL db operations under the `backend/onyx/db` / `backend/ee/onyx/db` directories. Don't run queries
  outside of those directories.

## STARWOOD DEV OPS NOTES

### Docker / Bake Commands

- Start web service for local/dev verification:
  - `./tools/bake.sh web --compose-up --compose-file docker-compose.dev.yml --compose-up-service web_server`
- Restart full dev stack with the dev compose override:
  - `./tools/bake.sh --compose-restart --compose-file docker-compose.dev.yml`
- For this repo, keep source builds pinned to local image names/tags (avoid `latest` drift):
  - `IMAGE_TAG=local-dev`
  - `BACKEND_REPOSITORY=onyx-local/onyx-backend`
  - `WEB_SERVER_REPOSITORY=onyx-local/onyx-web-server`
  - `MODEL_SERVER_REPOSITORY=onyx-local/onyx-model-server`
- `./tools/bake.sh --compose-restart` and `./tools/bake.sh --compose-restart --compose-file docker-compose.dev.yml` are **not always equivalent**.
  - Use the explicit `--compose-file docker-compose.dev.yml` form when working on the dev domain/TLS stack.
- Important: keep the full command on one line (or use `\` line continuations). A broken line like `--compose-up-service` on its own will be treated as a shell command and fail.

### Craft / Code Interpreter Setup (Source Builds)

- For this repo, enabling Craft requires both runtime env flags and a Craft-enabled backend image build.
- Required `.env` entries in `deployment/docker_compose/.env`:
  - `ENABLE_CRAFT=true`
  - `CODE_INTERPRETER_BETA_ENABLED=true`
  - `CODE_INTERPRETER_BASE_URL=http://code-interpreter:8000`
- Preferred build + restart path (uses `docker-bake.hcl` and dev compose):
  - `ENABLE_CRAFT=true ./tools/bake.sh backend --compose-restart --compose-file docker-compose.dev.yml`
- Compose fallback (if you need explicit direct compose build):
  - `cd deployment/docker_compose && ENABLE_CRAFT=true docker compose -f docker-compose.yml -f docker-compose.dev.yml build api_server background mcp_server`
  - `docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --force-recreate api_server background mcp_server code-interpreter web_server nginx`
- Verify:
  - `docker exec onyx-api_server-1 env | grep -E 'ENABLE_CRAFT|CODE_INTERPRETER_BASE_URL'`
  - `docker compose -f docker-compose.yml -f docker-compose.dev.yml logs --tail=120 code-interpreter`
  - `docker exec onyx-api_server-1 python -c "import urllib.request; print(urllib.request.urlopen('http://code-interpreter:8000/health').read().decode())"`
- Startup performance note:
  - `backend/scripts/setup_craft_templates.sh` is now idempotent and skips npm reinstall when template deps are already prepared.
  - Set `CRAFT_FORCE_TEMPLATE_NPM_INSTALL=true` only when you intentionally want to refresh template web deps.

### Admin IA Notes

- For Starwood admin navigation, keep these entry points under `User Management`:
  - `Usage Statistics` (`/admin/performance/usage`)
  - `Query History` (`/admin/performance/query-history`)
- Keep backend/frontend route paths unchanged (continue using `/admin/performance/*` URLs).
- `Performance` section (if shown) is reserved for `Custom Analytics`.

### Domain / Routing / TLS

- Dev app URL:
  - `https://dev.starwoodgpt.prosourceit.app/`
- In this project, API and MCP calls should go through the dev domain unless you are intentionally debugging container-internal networking.
- Quick health checks:
  - `curl -sS https://dev.starwoodgpt.prosourceit.app/api/health`
  - `curl -sS https://dev.starwoodgpt.prosourceit.app/mcp/health`

### Container Health Recovery

- MinIO healthchecks in compose should use `["CMD", "mc", "ready", "local"]`.
  - Why: `curl` is not guaranteed to exist in all MinIO server images and can cause false `unhealthy` status.
- If `onyx-index-1` is unhealthy with Vespa configserver lock/session errors, recover by:
  1. Stop `index` (and typically `api_server` while recovering).
  2. Back up then reset Vespa state paths on the Vespa volume:
     - `/vespa/db/vespa/config_server`
     - `/vespa/zookeeper/version-2`
  3. Start `index`, then restart `api_server` and `nginx`.
- Example backup/reset command:
  - `docker run --rm -v onyx_vespa_volume:/vespa alpine sh -lc 'ts=$(date +%Y%m%d%H%M%S); backup=/vespa/recovery-backup-$ts; mkdir -p "$backup"; cp -a /vespa/db/vespa/config_server "$backup"/config_server || true; cp -a /vespa/zookeeper/version-2 "$backup"/zookeeper-version-2 || true; rm -rf /vespa/db/vespa/config_server /vespa/zookeeper/version-2'`

### MCP + Microsoft Tools

- MCP server must be enabled in env (`MCP_SERVER_ENABLED=true`) and running.
- For mailbox tools, if local snapshots are missing, the Starwood MCP inbox tools are expected to fall back to live Microsoft Graph.
- If a user says inbox/calendar tools fail:
  1. Confirm user has a valid OAuth account/token in Onyx.
  2. Re-auth the Microsoft account if token/scope is stale.
  3. Start a new chat session after tool/config updates (session-level caching can hide updates).

### Zendesk KB (Important)

- Zendesk KB MCP tools rely on Chroma data and defaults aligned with deprecated setup:
  - Chroma path default: `onyx/zendesk/chroma`
  - Collection default: `zendesk_help_center`
- If `search_kb` fails with `chromadb is not installed`, the backend image/dependencies are out of sync.
- If `search_kb` returns empty, verify that the Chroma path exists in the running container and contains data.
- Inventory tool:
  - MCP tool `list_kb_articles` can return indexed Zendesk articles (`title`, `url`) for validation.
- Generated inventory snapshot from deprecated data is stored at:
  - `zendesk_kb_inventory.txt`

### Known Build Pitfall

- In some environments, Docker build may fail during Playwright dependency install with apt signature errors (`repository is not signed`).
- If this occurs, treat it as an infra/package mirror issue (not an app logic issue), and verify runtime containers directly while infra is fixed.

## Project Overview

**Onyx** (formerly Danswer) is an open-source Gen-AI and Enterprise Search platform that connects to company documents, apps, and people. It features a modular architecture with both Community Edition (MIT licensed) and Enterprise Edition offerings.

### Background Workers (Celery)

Onyx uses Celery for asynchronous task processing with multiple specialized workers:

#### Worker Types

1. **Primary Worker** (`celery_app.py`)
   - Coordinates core background tasks and system-wide operations
   - Handles connector management, document sync, pruning, and periodic checks
   - Runs with 4 threads concurrency
   - Tasks: connector deletion, vespa sync, pruning, LLM model updates, user file sync

2. **Docfetching Worker** (`docfetching`)
   - Fetches documents from external data sources (connectors)
   - Spawns docprocessing tasks for each document batch
   - Implements watchdog monitoring for stuck connectors
   - Configurable concurrency (default from env)

3. **Docprocessing Worker** (`docprocessing`)
   - Processes fetched documents through the indexing pipeline:
     - Upserts documents to PostgreSQL
     - Chunks documents and adds contextual information
     - Embeds chunks via model server
     - Writes chunks to Vespa vector database
     - Updates document metadata
   - Configurable concurrency (default from env)

4. **Light Worker** (`light`)
   - Handles lightweight, fast operations
   - Tasks: vespa operations, document permissions sync, external group sync
   - Higher concurrency for quick tasks

5. **Heavy Worker** (`heavy`)
   - Handles resource-intensive operations
   - Primary task: document pruning operations
   - Runs with 4 threads concurrency

6. **KG Processing Worker** (`kg_processing`)
   - Handles Knowledge Graph processing and clustering
   - Builds relationships between documents
   - Runs clustering algorithms
   - Configurable concurrency

7. **Monitoring Worker** (`monitoring`)
   - System health monitoring and metrics collection
   - Monitors Celery queues, process memory, and system status
   - Single thread (monitoring doesn't need parallelism)
   - Cloud-specific monitoring tasks

8. **User File Processing Worker** (`user_file_processing`)
   - Processes user-uploaded files
   - Handles user file indexing and project synchronization
   - Configurable concurrency

9. **Beat Worker** (`beat`)
   - Celery's scheduler for periodic tasks
   - Uses DynamicTenantScheduler for multi-tenant support
   - Schedules tasks like:
     - Indexing checks (every 15 seconds)
     - Connector deletion checks (every 20 seconds)
     - Vespa sync checks (every 20 seconds)
     - Pruning checks (every 20 seconds)
     - KG processing (every 60 seconds)
     - Monitoring tasks (every 5 minutes)
     - Cleanup tasks (hourly)

#### Worker Deployment Modes

Onyx supports two deployment modes for background workers, controlled by the `USE_LIGHTWEIGHT_BACKGROUND_WORKER` environment variable:

**Lightweight Mode** (default, `USE_LIGHTWEIGHT_BACKGROUND_WORKER=true`):

- Runs a single consolidated `background` worker that handles all background tasks:
  - Light worker tasks (Vespa operations, permissions sync, deletion)
  - Document processing (indexing pipeline)
  - Document fetching (connector data retrieval)
  - Pruning operations (from `heavy` worker)
  - Knowledge graph processing (from `kg_processing` worker)
  - Monitoring tasks (from `monitoring` worker)
  - User file processing (from `user_file_processing` worker)
- Lower resource footprint (fewer worker processes)
- Suitable for smaller deployments or development environments
- Default concurrency: 20 threads (increased to handle combined workload)

**Standard Mode** (`USE_LIGHTWEIGHT_BACKGROUND_WORKER=false`):

- Runs separate specialized workers as documented above (light, docprocessing, docfetching, heavy, kg_processing, monitoring, user_file_processing)
- Better isolation and scalability
- Can scale individual workers independently based on workload
- Suitable for production deployments with higher load

The deployment mode affects:

- **Backend**: Worker processes spawned by supervisord or dev scripts
- **Helm**: Which Kubernetes deployments are created
- **Dev Environment**: Which workers `dev_run_background_jobs.py` spawns

#### Key Features

- **Thread-based Workers**: All workers use thread pools (not processes) for stability
- **Tenant Awareness**: Multi-tenant support with per-tenant task isolation. There is a
  middleware layer that automatically finds the appropriate tenant ID when sending tasks
  via Celery Beat.
- **Task Prioritization**: High, Medium, Low priority queues
- **Monitoring**: Built-in heartbeat and liveness checking
- **Failure Handling**: Automatic retry and failure recovery mechanisms
- **Redis Coordination**: Inter-process communication via Redis
- **PostgreSQL State**: Task state and metadata stored in PostgreSQL

#### Important Notes

**Defining Tasks**:

- Always use `@shared_task` rather than `@celery_app`
- Put tasks under `background/celery/tasks/` or `ee/background/celery/tasks`

**Defining APIs**:
When creating new FastAPI APIs, do NOT use the `response_model` field. Instead, just type the
function.

**Testing Updates**:
If you make any updates to a celery worker and you want to test these changes, you will need
to ask me to restart the celery worker. There is no auto-restart on code-change mechanism.

**Task Time Limits**:
Since all tasks are executed in thread pools, the time limit features of Celery are silently 
disabled and won't work. Timeout logic must be implemented within the task itself.

### Code Quality

```bash
# Install and run pre-commit hooks
pre-commit install
pre-commit run --all-files
```

NOTE: Always make sure everything is strictly typed (both in Python and Typescript).

## Architecture Overview

### Technology Stack

- **Backend**: Python 3.11, FastAPI, SQLAlchemy, Alembic, Celery
- **Frontend**: Next.js 15+, React 18, TypeScript, Tailwind CSS
- **Database**: PostgreSQL with Redis caching
- **Search**: Vespa vector database
- **Auth**: OAuth2, SAML, multi-provider support
- **AI/ML**: LangChain, LiteLLM, multiple embedding models

### Directory Structure

```
backend/
├── onyx/
│   ├── auth/                    # Authentication & authorization
│   ├── chat/                    # Chat functionality & LLM interactions
│   ├── connectors/              # Data source connectors
│   ├── db/                      # Database models & operations
│   ├── document_index/          # Vespa integration
│   ├── federated_connectors/    # External search connectors
│   ├── llm/                     # LLM provider integrations
│   └── server/                  # API endpoints & routers
├── ee/                          # Enterprise Edition features
├── alembic/                     # Database migrations
└── tests/                       # Test suites

web/
├── src/app/                     # Next.js app router pages
├── src/components/              # Reusable React components
└── src/lib/                     # Utilities & business logic
```

## Frontend Standards

### 1. Import Standards

**Always use absolute imports with the `@` prefix.**

**Reason:** Moving files around becomes easier since you don't also have to update those import statements. This makes modifications to the codebase much nicer.

```typescript
// ✅ Good
import { Button } from "@/components/ui/button";
import { useAuth } from "@/hooks/useAuth";
import { Text } from "@/refresh-components/texts/Text";

// ❌ Bad
import { Button } from "../../../components/ui/button";
import { useAuth } from "./hooks/useAuth";
```

### 2. React Component Functions

**Prefer regular functions over arrow functions for React components.**

**Reason:** Functions just become easier to read.

```typescript
// ✅ Good
function UserProfile({ userId }: UserProfileProps) {
  return <div>User Profile</div>
}

// ❌ Bad
const UserProfile = ({ userId }: UserProfileProps) => {
  return <div>User Profile</div>
}
```

### 3. Props Interface Extraction

**Extract prop types into their own interface definitions.**

**Reason:** Functions just become easier to read.

```typescript
// ✅ Good
interface UserCardProps {
  user: User
  showActions?: boolean
  onEdit?: (userId: string) => void
}

function UserCard({ user, showActions = false, onEdit }: UserCardProps) {
  return <div>User Card</div>
}

// ❌ Bad
function UserCard({
  user,
  showActions = false,
  onEdit
}: {
  user: User
  showActions?: boolean
  onEdit?: (userId: string) => void
}) {
  return <div>User Card</div>
}
```

### 4. Spacing Guidelines

**Prefer padding over margins for spacing.**

**Reason:** We want to consolidate usage to paddings instead of margins.

```typescript
// ✅ Good
<div className="p-4 space-y-2">
  <div className="p-2">Content</div>
</div>

// ❌ Bad
<div className="m-4 space-y-2">
  <div className="m-2">Content</div>
</div>
```

### 5. Tailwind Dark Mode

**Strictly forbid using the `dark:` modifier in Tailwind classes, except for logo icon handling.**

**Reason:** The `colors.css` file already, VERY CAREFULLY, defines what the exact opposite colour of each light-mode colour is. Overriding this behaviour is VERY bad and will lead to horrible UI breakages.

**Exception:** The `createLogoIcon` helper in `web/src/components/icons/icons.tsx` uses `dark:` modifiers (`dark:invert`, `dark:hidden`, `dark:block`) to handle third-party logo icons that cannot automatically adapt through `colors.css`. This is the ONLY acceptable use of dark mode modifiers.

```typescript
// ✅ Good - Standard components use `tailwind-themes/tailwind.config.js` / `src/app/css/colors.css`
<div className="bg-background-neutral-03 text-text-02">
  Content
</div>

// ✅ Good - Logo icons with dark mode handling via createLogoIcon
export const GithubIcon = createLogoIcon(githubLightIcon, {
  monochromatic: true,  // Will apply dark:invert internally
});

export const GitbookIcon = createLogoIcon(gitbookLightIcon, {
  darkSrc: gitbookDarkIcon,  // Will use dark:hidden/dark:block internally
});

// ❌ Bad - Manual dark mode overrides
<div className="bg-white dark:bg-black text-black dark:text-white">
  Content
</div>
```

### 6. Class Name Utilities

**Use the `cn` utility instead of raw string formatting for classNames.**

**Reason:** `cn`s are easier to read. They also allow for more complex types (i.e., string-arrays) to get formatted properly (it flattens each element in that string array down). As a result, it can allow things such as conditionals (i.e., `myCondition && "some-tailwind-class"`, which evaluates to `false` when `myCondition` is `false`) to get filtered out.

```typescript
import { cn } from '@/lib/utils'

// ✅ Good
<div className={cn(
  'base-class',
  isActive && 'active-class',
  className
)}>
  Content
</div>

// ❌ Bad
<div className={`base-class ${isActive ? 'active-class' : ''} ${className}`}>
  Content
</div>
```

### 7. Custom Hooks Organization

**Follow a "hook-per-file" layout. Each hook should live in its own file within `web/src/hooks`.**

**Reason:** This is just a layout preference. Keeps code clean.

```typescript
// web/src/hooks/useUserData.ts
export function useUserData(userId: string) {
  // hook implementation
}

// web/src/hooks/useLocalStorage.ts
export function useLocalStorage<T>(key: string, initialValue: T) {
  // hook implementation
}
```

### 8. Icon Usage

**ONLY use icons from the `web/src/icons` directory. Do NOT use icons from `react-icons`, `lucide`, or other external libraries.**

**Reason:** We have a very carefully curated selection of icons that match our Onyx guidelines. We do NOT want to muddy those up with different aesthetic stylings.

```typescript
// ✅ Good
import SvgX from "@/icons/x";
import SvgMoreHorizontal from "@/icons/more-horizontal";

// ❌ Bad
import { User } from "lucide-react";
import { FiSearch } from "react-icons/fi";
```

**Missing Icons**: If an icon is needed but doesn't exist in the `web/src/icons` directory, import it from Figma using the Figma MCP tool and add it to the icons directory.
If you need help with this step, reach out to `raunak@onyx.app`.

### 9. Text Rendering

**Prefer using the `refresh-components/texts/Text` component for all text rendering. Avoid "naked" text nodes.**

**Reason:** The `Text` component is fully compliant with the stylings provided in Figma. It provides easy utilities to specify the text-colour and font-size in the form of flags. Super duper easy.

```typescript
// ✅ Good
import { Text } from '@/refresh-components/texts/Text'

function UserCard({ name }: { name: string }) {
  return (
    <Text
      {/* The `text03` flag makes the text it renders to be coloured the 3rd-scale grey */}
      text03
      {/* The `mainAction` flag makes the text it renders to be "main-action" font + line-height + weightage, as described in the Figma */}
      mainAction
    >
      {name}
    </Text>
  )
}

// ❌ Bad
function UserCard({ name }: { name: string }) {
  return (
    <div>
      <h2>{name}</h2>
      <p>User details</p>
    </div>
  )
}
```

### 10. Component Usage

**Heavily avoid raw HTML input components. Always use components from the `web/src/refresh-components` or `web/lib/opal/src` directory.**

**Reason:** We've put in a lot of effort to unify the components that are rendered in the Onyx app. Using raw components breaks the entire UI of the application, and leaves it in a muddier state than before.

```typescript
// ✅ Good
import Button from '@/refresh-components/buttons/Button'
import InputTypeIn from '@/refresh-components/inputs/InputTypeIn'
import SvgPlusCircle from '@/icons/plus-circle'

function ContactForm() {
  return (
    <form>
      <InputTypeIn placeholder="Search..." />
      <Button type="submit" leftIcon={SvgPlusCircle}>Submit</Button>
    </form>
  )
}

// ❌ Bad
function ContactForm() {
  return (
    <form>
      <input placeholder="Name" />
      <textarea placeholder="Message" />
      <button type="submit">Submit</button>
    </form>
  )
}
```

### 11. Colors

**Always use custom overrides for colors and borders rather than built in Tailwind CSS colors. These overrides live in `web/tailwind-themes/tailwind.config.js`.**

**Reason:** Our custom color system uses CSS variables that automatically handle dark mode and maintain design consistency across the app. Standard Tailwind colors bypass this system.

**Available color categories:**

- **Text:** `text-01` through `text-05`, `text-inverted-XX`
- **Backgrounds:** `background-neutral-XX`, `background-tint-XX` (and inverted variants)
- **Borders:** `border-01` through `border-05`, `border-inverted-XX`
- **Actions:** `action-link-XX`, `action-danger-XX`
- **Status:** `status-info-XX`, `status-success-XX`, `status-warning-XX`, `status-error-XX`
- **Theme:** `theme-primary-XX`, `theme-red-XX`, `theme-blue-XX`, etc.

```typescript
// ✅ Good - Use custom Onyx color classes
<div className="bg-background-neutral-01 border border-border-02" />
<div className="bg-background-tint-02 border border-border-01" />
<div className="bg-status-success-01" />
<div className="bg-action-link-01" />
<div className="bg-theme-primary-05" />

// ❌ Bad - Do NOT use standard Tailwind colors
<div className="bg-gray-100 border border-gray-300 text-gray-600" />
<div className="bg-white border border-slate-200" />
<div className="bg-green-100 text-green-700" />
<div className="bg-blue-100 text-blue-600" />
<div className="bg-indigo-500" />
```

### 12. Data Fetching

**Prefer using `useSWR` for data fetching. Data should generally be fetched on the client side. Components that need data should display a loader / placeholder while waiting for that data. Prefer loading data within the component that needs it rather than at the top level and passing it down.**

**Reason:** Client side fetching allows us to load the skeleton of the page without waiting for data to load, leading to a snappier UX. Loading data where needed reduces dependencies between a component and its parent component(s).

## Database & Migrations

### Running Migrations

```bash
# Standard migrations
alembic upgrade head

# Multi-tenant (Enterprise)
alembic -n schema_private upgrade head
```

### Creating Migrations

```bash
# Create migration
alembic revision -m "description"

# Multi-tenant migration
alembic -n schema_private revision -m "description"
```

Write the migration manually and place it in the file that alembic creates when running the above command.

## Testing Strategy

First, you must activate the virtual environment with `source .venv/bin/activate`.

There are 4 main types of tests within Onyx:

### Unit Tests

These should not assume any Onyx/external services are available to be called.
Interactions with the outside world should be mocked using `unittest.mock`. Generally, only
write these for complex, isolated modules e.g. `citation_processing.py`.

To run them:

```bash
pytest -xv backend/tests/unit
```

### External Dependency Unit Tests

These tests assume that all external dependencies of Onyx are available and callable (e.g. Postgres, Redis,
MinIO/S3, Vespa are running + OpenAI can be called + any request to the internet is fine + etc.).

However, the actual Onyx containers are not running and with these tests we call the function to test directly.
We can also mock components/calls at will.

The goal with these tests are to minimize mocking while giving some flexibility to mock things that are flakey,
need strictly controlled behavior, or need to have their internal behavior validated (e.g. verify a function is called
with certain args, something that would be impossible with proper integration tests).

A great example of this type of test is `backend/tests/external_dependency_unit/connectors/confluence/test_confluence_group_sync.py`.

To run them:

```bash
python -m dotenv -f .vscode/.env run -- pytest backend/tests/external_dependency_unit
```

### Integration Tests

Standard integration tests. Every test in `backend/tests/integration` runs against a real Onyx deployment. We cannot
mock anything in these tests. Prefer writing integration tests (or External Dependency Unit Tests if mocking/internal
verification is necessary) over any other type of test.

Tests are parallelized at a directory level.

When writing integration tests, make sure to check the root `conftest.py` for useful fixtures + the `backend/tests/integration/common_utils` directory for utilities. Prefer (if one exists), calling the appropriate Manager
class in the utils over directly calling the APIs with a library like `requests`. Prefer using fixtures rather than
calling the utilities directly (e.g. do NOT create admin users with
`admin_user = UserManager.create(name="admin_user")`, instead use the `admin_user` fixture).

A great example of this type of test is `backend/tests/integration/dev_apis/test_simple_chat_api.py`.

To run them:

```bash
python -m dotenv -f .vscode/.env run -- pytest backend/tests/integration
```

### Playwright (E2E) Tests

These tests are an even more complete version of the Integration Tests mentioned above. Has all services of Onyx
running, _including_ the Web Server.

Use these tests for anything that requires significant frontend <-> backend coordination.

Tests are located at `web/tests/e2e`. Tests are written in TypeScript.

To run them:

```bash
npx playwright test <TEST_NAME>
```

## Logs

When (1) writing integration tests or (2) doing live tests (e.g. curl / playwright) you can get access
to logs via the `backend/log/<service_name>_debug.log` file. All Onyx services (api_server, web_server, celery_X)
will be tailing their logs to this file.

## Security Considerations

- Never commit API keys or secrets to repository
- Use encrypted credential storage for connector credentials
- Follow RBAC patterns for new features
- Implement proper input validation with Pydantic models
- Use parameterized queries to prevent SQL injection

## AI/LLM Integration

- Multiple LLM providers supported via LiteLLM
- Configurable models per feature (chat, search, embeddings)
- Streaming support for real-time responses
- Token management and rate limiting
- Custom prompts and agent actions

## Creating a Plan

When creating a plan in the `plans` directory, make sure to include at least these elements:

**Issues to Address**
What the change is meant to do.

**Important Notes**
Things you come across in your research that are important to the implementation.

**Implementation strategy**
How you are going to make the changes happen. High level approach.

**Tests**
What unit (use rarely), external dependency unit, integration, and playwright tests you plan to write to
verify the correct behavior. Don't overtest. Usually, a given change only needs one type of test.

Do NOT include these: _Timeline_, _Rollback plan_

This is a minimal list - feel free to include more. Do NOT write code as part of your plan.
Keep it high level. You can reference certain files or functions though.

Before writing your plan, make sure to do research. Explore the relevant sections in the codebase.
