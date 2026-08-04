# Official LSS document template assets

Everything in this folder is the school's document branding. `services/branding.py`
loads it on import and applies it to **every** document the platform generates —
question papers, model/past papers, monthly, midterm and final exams, MCQ sheets,
assignments, worksheets, lesson plans, teacher notes and classroom activities — in
both PDF and Microsoft Word. No user ever selects or uploads a template.

| File | Required | Purpose |
| --- | --- | --- |
| `lss_logo.png` | yes | School crest drawn in the page header. Derived from the master `logo.jpg` with the pale backdrop flattened to white and cropped to the artwork. |
| `lss_template.pdf` | no | The official one-page template artwork. When present, generated PDF pages of matching page size are stamped straight onto it instead of using the drawn frame/header — the most faithful reproduction of the supplied template. Landscape documents fall back to the drawn frame unless a landscape template is supplied. |
| `lss_wordmark.ttf` | no | Blackletter face for the "Lahore School System" header wordmark. Without it the wordmark renders in Times-Bold. Only add a font the school is licensed to redistribute. |

Every path, plus the wording of the header and the copyright notice, can be
overridden with environment variables — see `LSS_*` in `.env.example`.

## Replacing an asset

`docker-compose.yml` bind-mounts this folder into the backend at `/app/assets`,
so dropping a new file here and restarting the backend is enough; no rebuild is
needed.

## Changing the layout

Page geometry (border inset, margins, logo size, footer baselines) lives in the
constants at the top of `services/branding.py` and is shared by the PDF and Word
renderers, so a change there keeps the two exports in step.
