import json
import re

with open("out_csse1001.txt", "r") as f:
    contents = f.read()

# Remove any comments after the data

# Extract the array between courseSECATData = [ ... ];
match = re.search(r"courseSECATData\s*=\s*(\[.*\])\s*;", contents, re.DOTALL)

if not match:
    raise ValueError("Could not find courseSECATData array in the file")

json_text = match.group(1)

# Convert the JSON text into Python data
courseSECATData = json.loads(json_text)

# Get Q8 results
q8_results = [
    item for item in courseSECATData
    if item["QUESTION_NAME"].startswith("Q8")
]

# Sort by answer number: 1, 2, 3, 4, 5
q8_results = sorted(q8_results, key=lambda x: int(x["ANSWER"].split()[0]))

for result in q8_results:
    print(
        result["ANSWER"],
        "- Count:",
        result["VALUE"],
        "- Percent:",
        round(result["PERCENT_ANSWER"], 2),
        "%"
    )