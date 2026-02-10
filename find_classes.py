import re
import os

target_file = r'g:\다른 컴퓨터\내 컴퓨터\google antigravity\navernews-tabsearch\news_scraper_pro.py'
if not os.path.exists(target_file):
    print("File not found")
    exit()

with open(target_file, 'r', encoding='utf-8') as f:
    lines = f.readlines()

for i, line in enumerate(lines):
    if line.strip().startswith('class '):
        with open('classes_list.txt', 'a', encoding='utf-8') as out:
            out.write(f"{i+1}: {line.strip()}\n")
