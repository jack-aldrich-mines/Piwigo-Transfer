import csv
import os
import re

import requests
from dotenv import load_dotenv
from tqdm import tqdm


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


def main():
    login()

    try:
        with open('failed_update_desc.tsv', 'w', encoding='utf-8') as f:
            w = csv.writer(f, delimiter='\t')
            w.writerow(["image_id", "title", "error", "url"])

            # load most recent image id
            recent_id = -1
            try:
                info = api_post("pwg.categories.getImages", {'per_page': 1, 'order': 'date_available desc'})
                recent_id = info.get('images', [])[0]['id']
                print(f"Most recent ID: {recent_id}")
            except Exception as e:
                print(f"Failed to load recent image id: {str(e)}")
                return

            # load oldest image id
            try:
                info = api_post("pwg.categories.getImages", {'per_page': 1, 'order': 'date_available'})
                oldest_id = info.get('images', [])[0]['id']
                print(f"Oldest ID: {oldest_id}")
            except Exception as e:
                print(f"Failed to load oldest image id: {str(e)}")
                return

            # for every image, check desc
            status = ""
            ok_count = 0
            bad_count = 0
            alt_text_re = re.compile(r"Alt\s*Text\s*:", re.IGNORECASE)
            for image_id in tqdm(range(oldest_id, recent_id)):
                for attempt in range(3): # give an image three attempts to work
                    try:
                        info = api_post("pwg.images.getInfo", {"image_id": image_id})
                        title = info.get('title')
                        desc = info.get('description')
                        url = f"https://mines.piwigo.com/picture?/{image_id}"

                        if not desc.strip():
                            status = "MISSING DESCRIPTION"
                            bad_count += 1
                        else:
                            has_alt_text = bool(alt_text_re.search(desc))
                            if has_alt_text:
                                status = "OK"
                                ok_count += 1
                            else:
                                status = "MISSING CUSTOM DESCRIPTION"
                                bad_count += 1

                        if status != "OK":
                            w.writerow([image_id, title, status, url])

                        break

                    except Exception as e:
                        pass
                else:
                    tqdm.write(f"Failed to load image after 3 attempts.")

            print(f"Good: {ok_count}, Bad: {bad_count}")

    finally:
        logout()

if __name__ == "__main__":
    main()
