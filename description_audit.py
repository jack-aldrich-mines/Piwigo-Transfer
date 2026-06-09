import csv
import os
import re
import requests
from dotenv import load_dotenv

try:
    from tqdm import tqdm
except ImportError:
    tqdm = None


load_dotenv()
PIWIGO_USER = os.getenv("USERNAME")
PIWIGO_PASSWORD = os.getenv("PASSWORD")
if not PIWIGO_USER or not PIWIGO_PASSWORD:
    raise ValueError("Piwigo credentials not found.")
session = requests.Session()

BASE_URL = "https://mines.piwigo.com/ws.php?format=json"


def api_post(method: str, data: dict = None, files=None):
    payload = {'method': method, **(data or {})}
    r = session.post(
        BASE_URL,
        data=payload,
        files=files,
        timeout=30,
    )

    text = r.text or ''
    if r.status_code != 200:
        raise RuntimeError(f'HTTP {r.status_code} from Piwigo: {text[:300]}')

    try:
        js = r.json()
    except Exception:
        raise RuntimeError(f'Non-JSON response from Piwigo: {text[:300]}')

    if js.get('stat') == 'fail':
        raise RuntimeError(f"{method} failed: {js.get('err')} {js.get('message')}")

    return js['result']

def login():
    api_post('pwg.session.login', {
        'username': PIWIGO_USER,
        'password': PIWIGO_PASSWORD,
    })

def logout():
    api_post('pwg.session.logout')


def extract_title_and_description(info: dict) -> tuple[str, str]:
    if not isinstance(info, dict):
        return "", ""

    title = (
        info.get("name")
        or info.get("title")
        or info.get("file")
        or ""
    )

    description = (
        info.get("comment")
        or info.get("description")
        or info.get("commentary")
        or ""
    )

    return str(title), str(description)


def load_piwigo_ids_from_completed(path="completed.tsv") -> list[str]:
    ids = []
    with open(path, "r", newline="", encoding="utf-8") as f:
        reader = csv.reader(f, delimiter="\t")
        next(reader, None)  # header
        for row in reader:
            if not row:
                continue
            if len(row) < 8:
                continue
            pid = (row[7] or "").strip()
            if pid:
                ids.append(pid)

    # de-dupe while preserving order
    seen = set()
    out = []
    for pid in ids:
        if pid not in seen:
            seen.add(pid)
            out.append(pid)
    return out


def main():
    login()

    try:
        piwigo_ids = load_piwigo_ids_from_completed("completed.tsv")
        if not piwigo_ids:
            print("No Piwigo IDs found in completed.tsv")
            return

        report_path = "description_pattern_audit.tsv"
        with open(report_path, "w", newline="", encoding="utf-8") as out_f:
            w = csv.writer(out_f, delimiter="\t")
            w.writerow(["PiwigoID", "Title", "DescriptionHasAltText", "Status"])

            iterator = piwigo_ids
            if tqdm is not None:
                iterator = tqdm(piwigo_ids, desc="Auditing descriptions", unit="img")

            ok_count = 0
            missing_desc = 0
            missing_custom = 0
            error_count = 0

            alt_text_re = re.compile(r"Alt\s*Text\s*:", re.IGNORECASE)

            for image_id in iterator:
                try:
                    info = api_post("pwg.images.getInfo", {"image_id": image_id})
                    title, desc = extract_title_and_description(info)

                    if not desc.strip():
                        status = "MISSING_DESCRIPTION"
                        has_alt_text = False
                        missing_desc += 1
                    else:
                        has_alt_text = bool(alt_text_re.search(desc))
                        if has_alt_text:
                            status = "OK"
                            ok_count += 1
                        else:
                            status = "MISSING_CUSTOM_DESCRIPTION"
                            missing_custom += 1

                    # Don't dump the full description into the TSV (it can be huge / multiline).
                    # We just record whether the marker exists.
                    w.writerow([image_id, title, "YES" if has_alt_text else "NO", status])

                    if tqdm is None and status != "OK":
                        print(f"{status}: {image_id}")

                except Exception as e:
                    error_count += 1
                    w.writerow([image_id, "", "NO", f"ERROR: {e}"])
                    if tqdm is None:
                        print(f"ERROR: {image_id}: {e}")

        print(f"Wrote report: {report_path}")
        print(f"OK: {ok_count}")
        print(f"Missing description: {missing_desc}")
        print(f"Missing custom marker (Alt Text:): {missing_custom}")
        print(f"Errors: {error_count}")

    finally:
        logout()


if __name__ == "__main__":
    main()
