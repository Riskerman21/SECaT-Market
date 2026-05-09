from playwright.sync_api import sync_playwright

def getCourseData(courseCode: str, sem:int, year: int):
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto("https://www.pbi.uq.edu.au/clientservices/SECaT/embedChart.aspx")


        page.on("response", lambda r: r)

    def get_course_data(letter, course, course_code, course_code_semester_descr):
        page.click(f"text={letter}")
        page.click(f"text={course}")
        page.click(f"text={course_code}")
        page.click(f"text={course_code_semester_descr}")
        return page.content()

        page.click(f"text={courseCode[:1]}")
        page.click(f"text={courseCode[:4]}")
        page.click(f"text={courseCode}")
        page.wait_for_timeout(500)
        page.click(f"text={courseCode}: Semester {sem}, {year}")
        page.wait_for_timeout(500)

        content = page.content()


        data = (content[content.find("courseSECATData"): content.find("var title = '")])
        browser.close()
        return data
