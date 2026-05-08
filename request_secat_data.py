from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page()
    page.goto("https://www.pbi.uq.edu.au/clientservices/SECaT/embedChart.aspx")


    page.on("response", lambda r: print(r.url, r.status))


    page.click("text=C")
    page.click("text=CSSE")
    page.click("text=CSSE1001")




    content = page.content()


    data = (content[content.find("courseSECATData"): content.find("var title = '")])
    with open("out_csse1001.txt", "w") as f:
        f.write(data)
    browser.close()