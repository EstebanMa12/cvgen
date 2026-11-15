# cvgen

`cvgen` builds a Harvard-style CV as DOCX and PDF from a small Markdown dialect, checks that every technology, employer, title, date and number still exists in a source file you control, and can tailor that CV to a job posting without adding facts.

The example workspace is fictional. Avery Quinn, Northwind Labs, Harbor & Co., Bramble Institute of Technology, Maplepath Academy, Lantern and Lumenfield are not real.

## Install

Python 3.11 or newer:

```bash
pipx install .
```

From a checkout, extras install the optional provider SDKs. The base install is only `python-docx`.

```bash
pipx install '.[openai]'          # OpenAI
pipx install '.[anthropic]'       # Anthropic
pipx install '.[gemini]'          # Google Gemini (google-genai)
pipx install '.[all]'             # all three SDKs
```

Ollama and any other OpenAI-compatible server need no extra. The Cursor provider needs Node.js 22+ and a one-time `npm install` (see below). It is not a Python dependency.

API keys are read from the environment. `cvgen` refuses to load a config file that contains a key.

## LibreOffice

PDF export and the page-count check use LibreOffice in headless mode (`soffice` or `libreoffice`). `pdfinfo` from Poppler is used when it is installed; otherwise `cvgen` counts pages from the PDF itself.

```bash
# Debian / Ubuntu
sudo apt install libreoffice-writer poppler-utils

# Fedora
sudo dnf install libreoffice-writer poppler-utils

# macOS
brew install --cask libreoffice
brew install poppler
```

`cvgen build` still writes the DOCX when LibreOffice is missing, and it says so. Pass `--require-pdf` to fail instead, or `--no-pdf` to skip export on purpose.

Page limits are 1 page for `short` and 2 pages for `extended`. If a CV overflows, `cvgen` shrinks type size and spacing in small steps down to 9 pt (`short`) or 9.5 pt (`extended`). If it still does not fit, the command exits with status 1 so you can cut the Markdown. It does not silently spill onto an extra page.

## Quickstart

In a terminal, `cvgen` opens a Dracula-colored screen (purple, pink, and cyan on `#282a36`). The base install stays limited to `python-docx`. The screen itself is the `ui` extra:

```bash
pipx install '.[ui]'
cvgen
```

The start screen is centered, like the Grok Build CLI: a braille logo, a short menu with the shortcut on the right, a rounded prompt along the bottom, and the version in the corner.

```text
        ⢀⣀⣤⣤⣀⡀
     ⢀⣴⣿⣿⣿⣿⣿⣿⣦⡀
           cvgen

 > Build all            ctrl+b
   Verify all           ctrl+y
   Tailor to a job      ctrl+t
   Dashboard            ctrl+d
   New workspace        ctrl+n
   Quit                 ctrl+q

 ╭──────────────────────────────────────────────╮
 │ >  /tailor jobs/posting.txt            cvgen │
 ╰──────────────────────────────────────────────╯
                                              0.1.0
```

Type `/` for suggestions, or press `ctrl+p` for the command palette. `/tailor jobs/role.txt` opens the tailor dialog with that file. A path without a slash does the same.

`ctrl+d` opens the dashboard. The variant table and page meters sit on the left. The latest check and the match scores for each tailored CV (`met`, `partial`, `missing`) sit on the right. `j` and `k` move, `b` builds the row, `v` checks it, `t` opens the tailor dialog, and `esc` returns. Build and verify results open in a popup. The first-run folder setup is that same dialog, step by step. Shortcuts can be aliased in `cvgen.toml` under `[ui.keys]`, for example `build_all = "f2"`.

Without a terminal, `cvgen` prints the command help. `cvgen init`, `cvgen build`, `cvgen verify`, and `cvgen tailor` stay non-interactive.

The shell commands do the same work:

```bash
cvgen init
cvgen build
cvgen verify
cvgen tailor --job jobs/lumenfield-backend.txt --lang en --length short --dry-run
```

`cvgen init` writes:

- `cvgen.toml` — paths, page limits, the AI provider and per-variant keyword rules
- `source/consolidated.md` — the only facts the example CVs are allowed to use
- `cv/avery-quinn-{short,extended}-{en,es}.md` — four base CVs
- `jobs/lumenfield-backend.txt` — a fictional posting used by `tailor`

`cvgen build` with no arguments renders every variant in `cvgen.toml` into `out/`. `cvgen verify` checks those Markdown files (and a sibling or built PDF, when one exists).

## Markdown

```markdown
# Avery Quinn
> Backend Engineer | Python · FastAPI
Port Meridian | avery.quinn@example.com | +1 555 010 0199
linkedin.com/in/avery-quinn | github.com/avery-quinn

## EXPERIENCE
**Northwind Labs** | Port Meridian
*Software Engineer | March 2021 – Present*
- Shipped a **FastAPI** service.
*Technologies: Python, FastAPI, PostgreSQL*

## SKILLS
- **Backend:** FastAPI, PostgreSQL

<!-- Comments are kept in the file and never printed. -->
```

- `# Name` is the centered name. A following `> ` line is the headline under it.
- Lines before the first `## ` are contact lines. Emails, phones, LinkedIn, GitHub and GitLab become links. `[label](https://...)` works too.
- `**Left** | Right` is a bold entry with the right-hand side aligned to the margin. `**Left**` alone is a bold entry with no right-hand side.
- `*Left | Right*` is an italic role and date. An italic line with no `|` is a technologies line.
- `- item` is a bullet. Inline `**bold**` and `*italic*` are kept.
- `<!-- ... -->` is omitted from the DOCX, including when it spans several lines.

Section titles used by the fact checker:

| Kind | Heading starts with |
| --- | --- |
| Experience | `EXPERIENCE`, `EXPERIENCIA`, `WORK` |
| Education | `EDUCATION`, `FORMACIÓN ACADÉMICA`, `EDUCACIÓN` |
| Projects | `PROJECT`, `PROYECTO` |
| Skills | `SKILLS`, `HABILIDADES` |
| Certifications | contains `CERTIF` |

Spanish headings such as `PERFIL PROFESIONAL` and `IDIOMAS` select the Spanish document language for DOCX metadata. The locale strings live in `cvgen.toml` (`build.locale_es`, `build.locale_en`).

## How the fact check works

`cvgen verify` is the guarantee behind tailoring. A model may reorder, drop and rephrase. It may not introduce a technology, employer, institution, role title, date or number that the consolidated source does not already contain.

For each CV the checker:

1. Parses the Markdown, or rebuilds the same structure from a DOCX that `cvgen build` wrote.
2. Compares structured fields with the source after case-folding and dash normalization. Employers and schools come from bold entry lines. Role titles and their dates come from italic `*Role | Dates*` lines. Project names, skill tokens and certification names are checked the same way. The whole value has to occur in the source, so changing `Software Engineer` to `Senior Software Engineer` fails.
3. Scans the whole CV for a built-in list of common technologies (`Oracle`, `Kubernetes`, `React`, and the rest). A hit that is not also in the source is a `FACT` error, including when the word only appears inside a bullet. Extend the list with `verify.extra_known_tech` in `cvgen.toml`.
4. Finds month-and-year dates in English and Spanish, and every number. Decorated numbers such as `30%`, `12+` and `~15` must appear with that same decoration.
5. Applies keyword rules from the config. `verify.forbidden` is a word-boundary list (the example forbids `TODO`, `lorem` and `placeholder`). `verify.required.<variant id>` lists phrases that only the matching base CV must contain. `person.name` must appear in every CV. Extra phrases can be passed with `--require`.
6. Warns about HTML comments. They are not printed, and a warning does not fail the command. A sibling PDF that is over the page limit does fail.

`cvgen tailor` writes the CV, runs this check, and if it fails asks the model once to repair only the reported lines. A second failure exits with status 3 and leaves the Markdown in place for you to edit. The match report (`out/tailored/<slug>-<lang>-<length>-report.md`) lists requirements that are met, partial or missing. Missing tools belong in that report, not on the CV. Do not point `cvgen verify` at the report: it is supposed to name technologies the source does not contain.

The example posting asks for Kubernetes and Oracle PL/SQL on purpose. Neither is in `source/consolidated.md`, so a tailored CV that adds them fails verification.

## Providers

Set the provider in `cvgen.toml` under `[tailor]`, or pass `--provider` for one run. `--model` overrides the configured model. When you switch provider on the command line and do not pass `--model`, `cvgen` uses that provider's default model instead of the model name stored for the other provider.

| Provider | Extra | API key | Default model |
| --- | --- | --- | --- |
| `openai` | `cvgen[openai]` | `OPENAI_API_KEY` | `gpt-4o-mini` |
| `anthropic` | `cvgen[anthropic]` | `ANTHROPIC_API_KEY` | `claude-sonnet-4-5` |
| `gemini` | `cvgen[gemini]` | `GEMINI_API_KEY` or `GOOGLE_API_KEY` | `gemini-2.5-flash` |
| `cursor` | Node.js 22+ and `@cursor/sdk` | `CURSOR_API_KEY` | `composer-2` |
| `ollama` | none | none | `llama3.1` |
| `openai-compatible` | none | optional, `OPENAI_API_KEY` or `tailor.api_key_env` | `llama3.1` |

`tailor.api_key_env` is the **name** of a variable, never the key. `tailor.base_url` is the server root for `ollama` (default `http://127.0.0.1:11434/v1`) and for `openai-compatible`. A bare host such as `http://127.0.0.1:11434` is accepted. You can also point the OpenAI SDK at a compatible server by setting `base_url` and `--provider openai`.

Aliases: `google` → `gemini`, `local` → `ollama`.

### Cursor

The official Cursor SDK is TypeScript. `cvgen` ships a small runner, `cursor_agent.mjs`, and on a real tailor run copies it to `~/.cache/cvgen/cursor-sdk` (override with `CVGEN_CURSOR_HOME`). Install the SDK there once:

```bash
npm install --prefix ~/.cache/cvgen/cursor-sdk
export CURSOR_API_KEY="cursor_..."
cvgen tailor --provider cursor --job jobs/lumenfield-backend.txt --lang en --length short
```

If the cache directory does not exist yet, run any `cvgen tailor --provider cursor` command once. It writes `package.json` and then tells you the exact `npm install` command. The agent is started with read-only tools. The key is passed on stdin and is not written into the workspace.

### Ollama

```bash
# tailor.provider = "ollama" in cvgen.toml, or:
cvgen tailor --provider ollama --model llama3.1 --job jobs/lumenfield-backend.txt --lang es --length short
```

### Dry run

`--dry-run` writes the full prompt to `out/tailored/<slug>-<lang>-<length>.prompt.md` and does not call a provider. Use it to see exactly what would be sent.

Tailor exit codes: `0` ok, `1` configuration or authentication, `2` the model failed or returned no CV, `3` the fact check still fails after one repair, `4` DOCX/PDF generation failed.

## Commands

```bash
cvgen                  # interactive screen (needs the ui extra and a terminal)
cvgen ui
cvgen init [--dir DIR] [--force]
cvgen build [VARIANT ...] [--input FILE --output FILE] [--length short|extended] [--no-pdf] [--require-pdf] [--no-autofit]
cvgen verify [FILE ...] [--source FILE] [--require TEXT]
cvgen tailor --job FILE_OR_URL --lang es|en --length short|extended \
    [--provider NAME] [--model ID] [--slug NAME] [--base-url URL] [--dry-run] [--no-generate]
cvgen --config path/to/cvgen.toml build
cvgen --version
```

`cvgen.toml` is discovered from the current directory upward. Paths inside it are relative to the config file. `--config` may appear before or after the subcommand.

`cvgen build short-en` renders one configured variant. `cvgen build --input notes.md --length short` renders a single file and does not need a variant table.

## Development

```bash
python -m pip install -e '.[dev]'
python -m pytest
```

PDF tests are skipped when LibreOffice is not installed (`pytest -m pdf` runs only those).

## En español

`cvgen` convierte un currículum en Markdown a DOCX y PDF, comprueba que cada tecnología, empresa, cargo, fecha y número exista en un archivo fuente, y puede adaptar el CV a una vacante sin inventar datos.

Hace falta LibreOffice (`soffice`) para el PDF. Las claves de API solo se leen de variables de entorno (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `CURSOR_API_KEY`). El paquete base no instala los SDK de los proveedores; se añaden con `pipx install '.[openai]'`, `'.[anthropic]'` o `'.[gemini]'`. Ollama y cualquier API compatible con OpenAI no necesitan extra. Cursor usa un script de Node incluido en el paquete.

```bash
pipx install .
cvgen
cvgen init
cvgen build
cvgen verify
cvgen tailor --job jobs/lumenfield-backend.txt --lang es --length short --dry-run
```

En una terminal, `cvgen` abre una pantalla con la paleta Dracula. Hace falta el extra de interfaz: `pipx install '.[ui]'`. La primera vista es un menú centrado, con el atajo a la derecha y un prompt abajo (`/tailor jobs/archivo.txt`, o `ctrl+p` para la paleta). `ctrl+d` abre el tablero: variantes y medidores de página, el último chequeo y el encaje de cada CV adaptado (cumplido, parcial, faltante). Generar y verificar muestran el resultado en un cuadro. Si no hay workspace, un diálogo crea `source/`, `cv/`, `jobs/` y `out/`. Sin terminal, `cvgen` imprime la ayuda. `cvgen init`, `build`, `verify` y `tailor` siguen siendo comandos directos.

`cvgen init` crea un ejemplo con una persona ficticia, Avery Quinn, y empresas ficticias. `short` debe caber en una página y `extended` en dos. Si el texto no cabe, el programa reduce la letra hasta un mínimo (9 pt en la versión corta, 9,5 pt en la extendida) y, si aún se pasa, termina con error para que recortes el Markdown.

La verificación compara cargos, empresas, fechas y números con `source/consolidated.md`, y además busca una lista de tecnologías habituales en todo el texto. Adaptar una vacante solo puede reordenar, reformular y elegir hechos de esa fuente. Si el modelo añade algo que no está, `cvgen verify` lo marca como `FACT` y `cvgen tailor` pide una sola corrección. Lo que la vacante pide y la fuente no tiene va al informe de encaje, no al CV.

El proveedor se elige en `cvgen.toml` o con `--provider`: `openai`, `anthropic`, `gemini`, `cursor`, `ollama` u `openai-compatible`. `--dry-run` solo escribe el prompt.
