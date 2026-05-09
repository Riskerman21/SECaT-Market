import json
import re
import request_secat_data


def outToData(courseName: str, sem: int, year: int, questionNum: int):
    response = request_secat_data.getCourseData(courseName, sem, year)

    print(f"\nAvailable offerings for {response['course']}:")
    for offering in response["available_offerings"]:
        print("-", offering)

    if response["error"] is not None:
        raise ValueError(response["error"])

    contents = response["data"]

    match = re.search(r"courseSECATData\s*=\s*(\[.*\])\s*;", contents, re.DOTALL)

    if not match:
        raise ValueError("Could not find courseSECATData array in the file")

    json_text = match.group(1)

    courseSECATData = json.loads(json_text)

    q_results = [
        item for item in courseSECATData
        if item["QUESTION_NAME"].startswith(f"Q{questionNum}:")
    ]

    q_results = sorted(q_results, key=lambda x: int(x["ANSWER"].split()[0]))

    return q_results

response = request_secat_data.getCourseData("COMP3301")

print(response["available_offerings"])