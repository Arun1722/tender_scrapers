from flask import Flask, jsonify
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
from bs4 import BeautifulSoup
import re
import time
import pymongo
import threading
from datetime import datetime

app = Flask(__name__)

def is_valid_date(date_text):
    try:
        datetime.strptime(date_text, '%d-%m-%Y')
        return True
    except ValueError:
        return False

def parse_date(date_str):
    try:
        return datetime.strptime(date_str, '%d-%m-%Y')
    except ValueError:
        return None

# Function to scrape tenders for a given keyword
def scrape_tenders_for_keyword(keyword):
    # Set up Chrome options
    options = webdriver.ChromeOptions()
    options.add_argument('--headless')  # Run in headless mode
    options.add_argument('--disable-gpu')  # Disable GPU acceleration (useful for headless)
    options.add_argument('--no-sandbox')  # Bypass OS security model
    options.add_argument('--disable-dev-shm-usage')  # Overcome limited resource problems

    browser = webdriver.Chrome(options=options)

    url = f'https://www.tender247.com/keyword/{keyword}'
    browser.get(url)

    # Close the pop-up
    try:
        close_button_selector = '#closeInqueryFrom'
        close_button = WebDriverWait(browser, 20).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, close_button_selector))
        )
        close_button.click()
    except TimeoutException:
        print("No pop-up appeared within 20 seconds or couldn't locate the close button")

    time.sleep(5)
    browser.execute_script("window.scrollTo(0, document.body.scrollHeight);")
    time.sleep(5)

    try:
        known_element = WebDriverWait(browser, 30).until(
            EC.presence_of_element_located((By.CLASS_NAME, 'tender_inner_tr'))
        )
        print("Page content loaded after scrolling!")
    except TimeoutException:
        print("Content still did not load within 30 seconds after scrolling.")
        browser.quit()
        return []

    page_source = browser.page_source
    soup = BeautifulSoup(page_source, 'html.parser')
    tender_rows = soup.find_all('tr', {'class': 'tender_inner_tr'})
    all_tender_data = []

    for row in tender_rows:
        current_tender = {}
        t247_id_elem = row.find('td', class_='fontColor')
        if t247_id_elem:
            t247_id_text = t247_id_elem.text.strip().replace(u'\xa0', u' ')
            t247_id_match = re.search(r'T247 ID\s*:\s*(\d+)', t247_id_text)
            if t247_id_match:
                current_tender['t247_id'] = t247_id_match.group(1)
            else:
                t247_id_match_2 = re.search(r'\d+', t247_id_text)
                if t247_id_match_2:
                    current_tender['t247_id'] = t247_id_match_2.group(0)

        corrigendum_elem = row.find('p', id='pReqBrief')
        if corrigendum_elem:
            current_tender['corrigendum'] = corrigendum_elem.text.strip().replace(u'\xa0', u' ')

        inr_value_elem = row.find('span', string=re.compile(r'INR.*CR\.'))
        if inr_value_elem:
            current_tender['inr_value'] = inr_value_elem.get_text(strip=True).replace(u'\xa0', u' ')
        else:
            refer_doc_elem = row.find('span', class_='fontColor', string="Refer Document")
            if refer_doc_elem:
                current_tender['inr_value'] = "Refer Document"
            else:
                br_elem = row.find('br')
                if br_elem:
                    inr_value = br_elem.find_next_sibling('span', class_='fontColor').get_text(strip=True).replace(u'\xa0', u' ')
                    current_tender['inr_value'] = inr_value
                else:
                    current_tender['inr_value'] = "Unknown"

        # Extract and format End Date
        end_date = None
        end_date_elem = row.find('span', style='color:#ff9600;')
        if end_date_elem:
            end_date_str = end_date_elem.text.strip()
            end_date = parse_date(end_date_str)
        else:
            # Try to extract end date from the <p> element with 'text-align:center;'
            p_elem = row.find('p', style='text-align:center;')
            if p_elem:
                span_elems = p_elem.find_all('span')
                for span in span_elems:
                    if 'color:#ff9600;' in span.get('style', ''):
                        span_text = span.get_text(strip=True)
                        end_date = parse_date(span_text)
                        if end_date:
                            break
            else:
                # Check for the alternate end date structure
                alt_p_elem = row.find('p', style='text-align:center; ')
                if alt_p_elem:
                    alt_span_elem = alt_p_elem.find('span', style=' color:#ff9600;')
                    if alt_span_elem:
                        alt_end_date_str = alt_span_elem.text.strip()
                        end_date = parse_date(alt_end_date_str)

        if end_date:
            current_tender['end_date'] = end_date
        else:
            current_tender['end_date'] = "Refer Document"

        location_elem_row = row.find_next_sibling('tr', class_='location_content')
        if location_elem_row:
            location_elem = location_elem_row.find('td', class_='tenderListingLocation')
            if location_elem:
                location_text = location_elem.get_text(strip=True).replace(u'\xa0', u' ')
                current_tender['location'] = location_text

        if current_tender.get('t247_id') and current_tender.get('inr_value') != 'Unknown' and current_tender.get('end_date') is not None:
            all_tender_data.append(current_tender)
    
    browser.quit()
    return all_tender_data

# Function to insert scraped data into MongoDB
def insert_into_mongodb(data, keyword):
    client = pymongo.MongoClient("mongodb+srv://arun:94u4vK58Mei1VSGS@cluster0.m50mnij.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0")
    db = client["tender_database"]
    tenders_collection = db[f"24/7_{keyword}"]

    for tender in data:
        existing_tender = tenders_collection.find_one({"t247_id": tender.get("t247_id")})
        if existing_tender:
            print(f"Tender with T247 ID {tender.get('t247_id')} already exists. Skipping...")
        else:
            tenders_collection.insert_one(tender)
            print(f"Tender with T247 ID {tender.get('t247_id')} added to the database.")

    print(f"Data inserted into MongoDB for keyword '{keyword}'.")

# Initialize scraping process
scraping_status = "Not started"

@app.route('/start_scraping/<keywords>', methods=['GET'])
def start_scraping(keywords):
    global scraping_status
    scraping_status = "Started"
    
    keywords_list = keywords.split(',')
    
    threads = []
    for keyword in keywords_list:
        thread = threading.Thread(target=scrape_and_insert, args=(keyword,))
        threads.append(thread)
        thread.start()
    
    for thread in threads:
        thread.join()
    
    scraping_status = "Finished"
    return "Scraping process has started."

def scrape_and_insert(keyword):
    tender_data = scrape_tenders_for_keyword(keyword)
    insert_into_mongodb(tender_data, keyword)
    print(tender_data)
    
@app.route('/status', methods=['GET'])
def get_status():
    global scraping_status
    return jsonify({"status": scraping_status})

if __name__ == '__main__':
    app.run(debug=True)
