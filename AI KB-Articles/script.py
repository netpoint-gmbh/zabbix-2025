import requests
import sys
import urllib3
import re
import os
from openai import OpenAI

# Disable warnings about insecure SSL/TLS connections
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ---------------------------
# Configuration
# ---------------------------

# Set your OpenAI API key here
client = OpenAI(api_key="[OpenAI Key]")

# Zabbix details
ZABBIX_API_URL = "https://mon.demo.de/api_jsonrpc.php"
ZABBIX_USERNAME = "svc_ai"
ZABBIX_PASSWORD = "xxxx"
# The name of the Template Group you want to search (change as needed)
TEMPLATE_GROUP_NAME = "Default"

# ServiceNow details
SERVICENOW_INSTANCE = "https://demo.service-now.com"
SERVICENOW_USERNAME = "svc_sn_zabbix"
SERVICENOW_PASSWORD = "xxxx"
SERVICENOW_KB_ID = "[KB SysID]"
SERVICENOW_CATEGORY_ID = "[Category SysID]"
SERVICENOW_KB_AUTHOR_ID = "[Author SysID]"

# Name of local HTML file containing article content (must be in the same folder as script)
HTML_FILE_NAME = "article_content.html"

# ---------------------------
# Zabbix API Function
# ---------------------------
def zabbix_api(method, params, token=None):
    """
    Calls the Zabbix API with a given method and parameters.
    - For user.login, no token is provided in the headers.
    - For other methods, the token is sent via the Authorization header.
    """
    payload = {
        "jsonrpc": "2.0",
        "method": method,
        "params": params,
        "id": 1
    }
    headers = {
        "Content-Type": "application/json-rpc",
        "Accept": "application/json",
    }
    if token and method != "user.login":
        # In modern Zabbix (starting 6.2+), the token is used as Bearer in Authorization
        headers["Authorization"] = f"Bearer {token}"

    try:
        response = requests.post(ZABBIX_API_URL, json=payload, headers=headers, verify=False)
        response.raise_for_status()
        response_json = response.json()
    except requests.RequestException as e:
        print(f"HTTP error calling Zabbix method '{method}': {e}")
        sys.exit(1)

    if "error" in response_json:
        print(f"Error calling Zabbix method '{method}': {response_json['error']}")
        sys.exit(1)

    return response_json["result"]

# ---------------------------
# Generate KB Content with OpenAI
# ---------------------------
def generate_kb_content_openai(trigger_name, template_name, base_html):
    """
    Calls the OpenAI API to produce an updated KB article in HTML form.
    Incorporates:
      - trigger_name
      - template_name
      - context_info (whatever knowledge you have about the trigger)
      - base_html (the original template)

    Returns a string containing the updated HTML.
    Adjust the prompt/model/parameters as needed.
    """
    # Construct your prompt
    prompt = (
        f"You are a helpful assistant with knowledge of Zabbix triggers."
        f"Use your own knowledge (or do a web search if possible) about '{trigger_name}' from the template '{template_name}'."
        f"Dont mention the template or trigger name in the content."
        f"Below is an existing HTML template for a ServiceNow Knowledge article:\n"
        f"{base_html}\n\n"
        "Please produce a final, refined HTML article that includes:\n"
        " - Explanation of what this Zabbix trigger does\n"
        " - Potential Steps for the first level to take before escalating to second lvl.\n"
        " - Escalation, the agent already has a ticket from that trigger in ServiceNow open.\n"
        " - Dont add anything to the Special cases section, this is done manually later on.\n"
        "Return only valid HTML (no markdown) and keep the original structure and design."
    )

    try:
        response = client.completions.create(model="gpt-3.5-turbo-instruct",
        prompt=prompt,
        max_tokens=1000,
        temperature=0.7)
        # The completed text should be our updated HTML
        updated_html = response.choices[0].text
        return updated_html.strip()

    except Exception as e:
        print(f"OpenAI API call failed: {e}")
        # Fallback: return the base HTML if there's an error
        return base_html

# ---------------------------
# ServiceNow: Create KB Article
# ---------------------------
def create_servicenow_kb_article(short_description, html_content):
    """
    Creates a new Knowledge article in ServiceNow with the given short_description (title)
    and html_content for the article body.
    Returns a dict with:
      {
          "sys_id": "...",
          "number": "KB000xxxx",
          "permalink": "https://..."
      }
    or None on failure.
    """
    url = f"{SERVICENOW_INSTANCE}/api/now/table/kb_knowledge"
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json"
    }

    data = {
        "short_description": short_description,
        "text": html_content,
        "kb_knowledge_base": SERVICENOW_KB_ID,
        "kb_category": SERVICENOW_CATEGORY_ID,
        "author": SERVICENOW_KB_AUTHOR_ID,
        "workflow_state": "published"
    }

    try:
        response = requests.post(
            url,
            auth=(SERVICENOW_USERNAME, SERVICENOW_PASSWORD),
            headers=headers,
            json=data,
            verify=False
        )
        response.raise_for_status()
    except requests.RequestException as e:
        print(f"Error creating KB article '{short_description}': {e}")
        return None

    result = response.json().get("result")
    if not result:
        print("No 'result' in ServiceNow response.")
        return None

    sys_id = result.get("sys_id")
    number = result.get("number")  # e.g. "KB0001234"
    # Build or retrieve your desired permalink. Often it's /kb_view.do?sys_kb_id=<sys_id>
    permalink = f"{SERVICENOW_INSTANCE}/kb_view.do?sys_kb_id={sys_id}"

    return {
        "sys_id": sys_id,
        "number": number,
        "permalink": permalink
    }

# ---------------------------
# Update Zabbix Trigger or Prototype
# ---------------------------
def update_zabbix_trigger(trigger_id, kb_number, kb_url, token, is_prototype=False):
    """
    Update a Zabbix trigger or trigger prototype by setting:
      - url_name = kb_number
      - url      = kb_url

    If is_prototype=True, calls triggerprototype.update.
    Otherwise, calls trigger.update.
    """
    params = {
        "triggerid": trigger_id,
        "url_name": kb_number,
        "url": kb_url
    }

    if is_prototype:
        method = "triggerprototype.update"
    else:
        method = "trigger.update"

    return zabbix_api(method, params, token)

# ---------------------------
# Get a Zabbix Group ID by Name
# ---------------------------
def get_zabbix_group_id_by_name(group_name, token):
    """
    Looks up the Zabbix group ID by exact group name.
    Returns the groupid or None if not found.
    """
    groups = zabbix_api("templategroup.get", {
        "output": ["groupid", "name"],
        "filter": {"name": group_name}
    }, token=token)

    if groups:
        return groups[0]["groupid"]
    return None

# ---------------------------
# Check if KB Article Exists in ServiceNow
# ---------------------------
def article_exists_in_servicenow(short_description):
    """
    Checks if a KB article already exists in ServiceNow for the given short_description.
    Returns True if found, False otherwise.
    """
    url = f"{SERVICENOW_INSTANCE}/api/now/table/kb_knowledge"
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json"
    }
    params = {
        "sysparm_query": f"short_description={short_description}",
        "sysparm_fields": "sys_id",
        "sysparm_limit": "1"
    }
    try:
        response = requests.get(
            url,
            auth=(SERVICENOW_USERNAME, SERVICENOW_PASSWORD),
            headers=headers,
            params=params,
            verify=False
        )
        response.raise_for_status()
    except requests.RequestException as e:
        print(f"Error while checking existing KB article: {e}")
        # If there's an error, treat it as 'not found' or you can return True to skip
        return False

    data = response.json().get("result", [])
    return len(data) > 0

# ---------------------------
# Main
# ---------------------------
def main():
    # 1. Authenticate with Zabbix
    print("Authenticating with Zabbix...")
    auth_token = zabbix_api("user.login", {
        "username": ZABBIX_USERNAME,
        "password": ZABBIX_PASSWORD
    })
    print("Authenticated successfully.")

    # 2. Get the group ID by name
    group_id = get_zabbix_group_id_by_name(TEMPLATE_GROUP_NAME, auth_token)
    if not group_id:
        print(f"Could not find a group with name '{TEMPLATE_GROUP_NAME}'. Aborting.")
        sys.exit(1)
    print(f"Found group '{TEMPLATE_GROUP_NAME}' with ID={group_id}.")

    # 3. Get templates in that group using template.get
    templates = zabbix_api("template.get", {
        "groupids": group_id,
        "output": ["templateid", "name"]
    }, token=auth_token)

    if not templates:
        print(f"No templates found in group '{TEMPLATE_GROUP_NAME}'. Nothing to do.")
        sys.exit(0)

    print(f"Retrieved {len(templates)} templates from group '{TEMPLATE_GROUP_NAME}'.")

    # 4. Gather all enabled triggers from those templates
    all_enabled_triggers = []
    for tpl in templates:
        tpl_id = tpl["templateid"]
        tpl_name = tpl["name"]

        # 4.1) Get all enabled triggers from the template
        triggers = zabbix_api("trigger.get", {
            "hostids": tpl_id,
            "output": ["triggerid", "description", "status", "url", "url_name"],
            "filter": {"status": "0"}  # 0 = enabled
        }, token=auth_token)

        if not triggers:
            continue

        for trig in triggers:
            all_enabled_triggers.append({
                "template_id": tpl_id,
                "template_name": tpl_name,
                "trigger_id": trig["triggerid"],
                "trigger_name": trig["description"],
                "trigger_menu_name": trig.get("url_name", ""),
                "trigger_menu_url": trig.get("url", ""),
                "is_prototype": False
            })

        # 4.2) Get all enabled trigger prototypes from the template
        prototypes = zabbix_api("triggerprototype.get", {
            "hostids": tpl_id,
            "output": ["triggerid", "description", "status", "url", "url_name"],
            "filter": {"status": "0"}  # 0 = enabled
        }, token=auth_token)
        if prototypes:
            for proto in prototypes:
                all_enabled_triggers.append({
                    "template_id": tpl_id,
                    "template_name": tpl_name,
                    "trigger_id": proto["triggerid"],
                    "trigger_name": proto["description"],
                    "trigger_menu_name": proto.get("url_name", ""),
                    "trigger_menu_url": proto.get("url", ""),
                    # Flag indicating that this is a trigger prototype
                    "is_prototype": True
                })

    # Print how many enabled triggers were found
    print(f"Found {len(all_enabled_triggers)} enabled triggers in group '{TEMPLATE_GROUP_NAME}'.")
    if not all_enabled_triggers:
        print("No enabled triggers to process. Exiting.")
        sys.exit(0)

    # 5. Load the HTML content from file
    if not os.path.isfile(HTML_FILE_NAME):
        print(f"HTML file '{HTML_FILE_NAME}' not found in current directory. Aborting.")
        sys.exit(1)

    with open(HTML_FILE_NAME, "r", encoding="utf-8") as f:
        base_html_content = f.read()

    # 6. Main loop over triggers
    for i, item in enumerate(all_enabled_triggers, start=1):
        trig_id = item["trigger_id"]
        trig_name = item["trigger_name"]
        tpl_name = item["template_name"]
        is_proto = item["is_prototype"]

        # 6.1) Check if KB article already exists in ServiceNow by short_description
        if article_exists_in_servicenow(trig_name):
            print(f"An article with short_description='{trig_name}' already exists. Skipping.")
            continue

        # 6.3) Generate refined HTML with OpenAI
        updated_html_content = generate_kb_content_openai(
            trigger_name=trig_name,
            template_name=tpl_name,
            base_html=base_html_content
        )

        # 6.4) Create the KB article in ServiceNow
        print(f"\nCreating KB article for trigger '{trig_name}' (Template: {tpl_name}) ...")
        kb_data = create_servicenow_kb_article(
            short_description=trig_name,
            html_content=updated_html_content
        )
        if not kb_data:
            print(f"Failed to create KB article for trigger '{trig_name}'. Skipping trigger update.")
            continue

        kb_number = kb_data["number"]      # e.g. "KB0001234"
        kb_url    = kb_data["permalink"]   # e.g. "https://instance/kb_view.do?sys_kb_id=xyz"

        print(f"ServiceNow KB article created: {kb_number} => {kb_url}")

        # 6.4) Update the Zabbix trigger with the KB reference
        print("Updating Zabbix trigger with KB reference...")
        update_result = update_zabbix_trigger(trig_id, kb_number, kb_url, auth_token, is_proto)

        if isinstance(update_result, dict) and "triggerids" in update_result:
            print(f"Successfully updated trigger ID={trig_id}.")
        else:
            print(f"Unexpected result updating trigger {trig_id}: {update_result}")

    print("\nDone. All triggers processed.")

if __name__ == "__main__":
    main()