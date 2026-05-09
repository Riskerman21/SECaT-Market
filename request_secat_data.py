from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError


def getCourseData(courseCode: str, sem: int | None = None, year: int | None = None):
    courseCode = courseCode.upper()

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()

        try:
            page.goto("https://www.pbi.uq.edu.au/clientservices/SECaT/embedChart.aspx")

            page.click(f"text={courseCode[:1]}")
            page.click(f"text={courseCode[:4]}")
            page.click(f"text={courseCode}")

            page.wait_for_timeout(500)

            offerings_locator = page.locator(f"text={courseCode}: Semester")
            offering_count = offerings_locator.count()

            if offering_count == 0:
                browser.close()
                return {
                    "course": courseCode,
                    "available_offerings": [],
                    "selected_offering": None,
                    "data": None,
                    "error": f"No offerings found for {courseCode}"
                }

            available_offerings = []

            for i in range(offering_count):
                offering_text = offerings_locator.nth(i).inner_text().strip()
                available_offerings.append(offering_text)

            # If user only wants to see available offerings
            if sem is None or year is None:
                browser.close()
                return {
                    "course": courseCode,
                    "available_offerings": available_offerings,
                    "selected_offering": None,
                    "data": None,
                    "error": None
                }

            target_offering = f"{courseCode}: Semester {sem}, {year}"

            matching_offering = page.locator(f"text={target_offering}")

            if matching_offering.count() == 0:
                browser.close()
                return {
                    "course": courseCode,
                    "available_offerings": available_offerings,
                    "selected_offering": None,
                    "data": None,
                    "error": f"{target_offering} is not available"
                }

            matching_offering.first.click()

            page.wait_for_timeout(500)

            content = page.content()

            start = content.find("courseSECATData")
            end = content.find("var title = '")

            if start == -1 or end == -1:
                browser.close()
                return {
                    "course": courseCode,
                    "available_offerings": available_offerings,
                    "selected_offering": target_offering,
                    "data": None,
                    "error": f"Could not find courseSECATData for {target_offering}"
                }

            data = content[start:end]

            browser.close()

            return {
                "course": courseCode,
                "available_offerings": available_offerings,
                "selected_offering": target_offering,
                "data": data,
                "error": None
            }

        except PlaywrightTimeoutError:
            browser.close()
            return {
                "course": courseCode,
                "available_offerings": [],
                "selected_offering": None,
                "data": None,
                "error": f"Timeout while loading {courseCode}"
            }

        except Exception as e:
            browser.close()
            return {
                "course": courseCode,
                "available_offerings": [],
                "selected_offering": None,
                "data": None,
                "error": str(e)
            }