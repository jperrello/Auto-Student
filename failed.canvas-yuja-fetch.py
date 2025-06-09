from canvasapi import Canvas
import re

# === Configuration ===
API_TOKEN="<token>"
CANVAS_BASE_URL = "<url>"
COURSE_ID = "<id>"
YUJA_DOMAIN = "<domain>"

# === Initialize Canvas ===
canvas = Canvas(CANVAS_BASE_URL, API_TOKEN)
course = canvas.get_course(COURSE_ID)

def extract_yuja_links_from_html(html):
    # Find iframe or anchor tags with YuJa links
    yuja_pattern = re.compile(rf'https://{re.escape(YUJA_DOMAIN)}/[^\s"\'<>]+')
    links = set(re.findall(yuja_pattern, html))

    # Try to extract video IDs from /V/ paths
    video_id_pattern = re.compile(r'/V/([^/?&"\'>]+)')
    video_ids = set()

    for link in links:
        match = video_id_pattern.search(link)
        if match:
            video_ids.add(match.group(1))

    return links, video_ids

def scan_course_content():
    all_links = set()
    all_video_ids = set()

    # === Pages ===
    print("Scanning pages...")
    pages = course.get_pages()
    try:
        for page in pages:
            full_page = course.get_page(page.url)
            html = full_page.body or ""
            links, video_ids = extract_yuja_links_from_html(html)
            all_links.update(links)
            all_video_ids.update(video_ids)
    except Exception as e:
        print(f"⚠️  Skipping pages due to error: {e}")

    # === Assignments ===
    print("Scanning assignments...")
    assignments = course.get_assignments()
    for assignment in assignments:
        html = assignment.description or ""
        links, video_ids = extract_yuja_links_from_html(html)
        all_links.update(links)
        all_video_ids.update(video_ids)

    return all_links, all_video_ids

def main():
    links, video_ids = scan_course_content()

    print("\n🎥 YuJa Video Links Found:")
    for link in sorted(links):
        print(link)

    print("\n🆔 Extracted Video IDs:")
    for vid in sorted(video_ids):
        print(vid)
    print("\nCourse dir:\n")
    print(dir(course))

    print("\nExternal tools:\n")
    tools = course.get_external_tools()
    for tool in tools:
        print(f"  {tool.name}: {tool.url}")

    print("\nYuja tool specifically\n")
    yuja_tool = course.get_external_tool(6825)
    print(f"  Name: {yuja_tool.name}")
    print(f"  URL: {yuja_tool.url}")


    print("\nCourse settings:\n")
    course_settings = course.get_settings()
    print(course_settings)


if __name__ == "__main__":
    main()

