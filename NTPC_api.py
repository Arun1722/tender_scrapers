import os
import cv2
import numpy as np
from time import sleep
from random import uniform
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from PIL import Image
import requests
from io import BytesIO
import easyocr
from selenium.common.exceptions import NoSuchElementException, TimeoutException, StaleElementReferenceException
import json
import pymongo
from flask import Flask, request, jsonify
import threading

app = Flask(__name__)
scraping_status = "Not Started"

class TenderAutomation:
    def __init__(self, keyword):
        options = webdriver.ChromeOptions()
        options.add_argument('--headless')
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        self.driver = webdriver.Chrome(options=options)
        self.client = pymongo.MongoClient("mongodb+srv://arun:94u4vK58Mei1VSGS@cluster0.m50mnij.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0")
        self.db = self.client["tender_database"]
        self.collection = self.db[f"ntpc_{keyword}"]  # Use keyword to set the collection name
        self.tender_details_list = []
        self.keyword = keyword

    def preprocess_image(self, image_path, img_height, img_width, save_folder, debug=False):
        img = Image.open(image_path)
        img_np = np.array(img.convert('L'))  # Convert to grayscale

        img_np = cv2.medianBlur(img_np, 3)
        _, img_np = cv2.threshold(img_np, 128, 255, cv2.THRESH_BINARY_INV)
        img_np = cv2.resize(img_np, (img_width, img_height))

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"preprocessed_{timestamp}.png"
        save_path = os.path.join(save_folder, filename)
        cv2.imwrite(save_path, img_np)

        return save_path

    def easy_ocr_captcha(self, latest_image_path):
        reader = easyocr.Reader(['en'])
        result = reader.readtext(latest_image_path)
        captcha_text = ' '.join([item[1] for item in result])
        return captcha_text

    def wait_between(self, a, b):
        rand = uniform(a, b)
        sleep(rand)

    def solve_captcha(self):
        captcha_image = WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.ID, "captchaImage"))
        )
        captcha_src = captcha_image.get_attribute('src')
        image_format = 'png' if '.png' in captcha_src.lower() else 'jpg'

        captcha_folder = 'captcha_images'
        os.makedirs(captcha_folder, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        captcha_image_path = os.path.join(captcha_folder, f'captcha_{timestamp}.{image_format}')

        if captcha_src.startswith('http'):
            response = requests.get(captcha_src)
            image = Image.open(BytesIO(response.content))
            image.save(captcha_image_path)
        else:
            captcha_image.screenshot(captcha_image_path)

        preprocessed_folder = 'pre_processed_captchas'
        os.makedirs(preprocessed_folder, exist_ok=True)
        preprocessed_image_path = self.preprocess_image(captcha_image_path, 50, 200, preprocessed_folder, debug=True)
        captcha_text = self.easy_ocr_captcha(preprocessed_image_path)

        print("Captcha Text:", captcha_text)  # Print the captcha text for debugging
        return captcha_text

    def automate_tender_search(self):
        self.driver.get("https://eprocurentpc.nic.in/nicgep/app?page=FrontEndLatestActiveTenders&service=page")

        tender_title_input = self.driver.find_element(By.ID, "TenderTitle")
        tender_title_input.send_keys(self.keyword)

        published_date_radio = self.driver.find_element(By.ID, "published")
        published_date_radio.click()

        captcha_attempts = 0
        max_attempts = 5

        while captcha_attempts < max_attempts:
            captcha_text = self.solve_captcha()
            captcha_input = self.driver.find_element(By.ID, "captchaText")
            captcha_input.send_keys(captcha_text)

            submit_button = self.driver.find_element(By.ID, "Submit")
            submit_button.click()

            self.wait_between(2, 4)  # Wait for some time to allow the page to load

            try:
                self.driver.find_element(By.CSS_SELECTOR, "span.error img[src='images/failure.png']")
                print("Invalid Captcha! Retrying...")
                captcha_attempts += 1
                self.wait_between(1, 2)  # Short wait before retrying
            except NoSuchElementException:
                print("Captcha solved successfully!")
                break
        else:
            print("Failed to solve captcha after multiple attempts.")
            self.driver.quit()
            return

        # Check if the tender table is present
        try:
            WebDriverWait(self.driver, 10).until(EC.presence_of_element_located((By.CLASS_NAME, "list_table")))
            print("Tender table found. Proceeding to parse the table.")
            self.parse_tender_table()
        except TimeoutException:
            print("Failed to load the tender table.")

        self.driver.quit()

        # Print all collected tender details
        print("Collected Tender Details:")
        print(self.tender_details_list)
        self.save_to_mongodb(self.tender_details_list)
        print("Saved to db")

    def save_to_mongodb(self, tender_details_list):
        for tender_details in tender_details_list:
            existing_tender = self.collection.find_one({"tender_reference_number": tender_details.get("tender_reference_number")})

            if existing_tender:
                print(f"Tender with Reference Number {tender_details.get('tender_reference_number')} already exists. Skipping...")
            else:
                self.collection.insert_one(tender_details)
                print(f"Tender with Reference Number {tender_details.get('tender_reference_number')} added to the database.")
                print("Tender Details saved to Mongo successfully")

    def parse_tender_table(self):
        rows_xpath = "//table[@class='list_table']//tr[contains(@id, 'informal')]"  # XPath to locate rows

        print(f"Starting to parse the tender table.")  # Debugging line
        
        # Iterate through each row and click the link
        for i in range(10):  # Assuming we want to process the first 10 rows
            try:
                # Refetch the rows to avoid stale element reference
                rows = self.driver.find_elements(By.XPATH, rows_xpath)

                if i == 0:
                    link_xpath = ".//a[@id='DirectLink']"
                else:
                    link_xpath = f".//a[@id='DirectLink_{i-1}']"

                link = rows[i].find_element(By.XPATH, link_xpath)
                print(f"Clicking link for row {i}: {link.get_attribute('href')}")  # Debugging line
                link.click()
                self.wait_between(1, 3)  # Wait for the tender details page to load
                self.extract_tender_details()
                
                # Use the provided XPath for the back button
                back_button = self.driver.find_element(By.XPATH, '//*[@id="DirectLink_11"]')
                back_button.click()
                self.wait_between(1, 3)  # Wait for the table to reload
            except NoSuchElementException as e:
                print(f"Error processing row {i}: {e}")
            except StaleElementReferenceException as e:
                print(f"Stale element reference for row {i}: {e}")
                # Refetch rows and continue
                self.wait_between(1, 3)
                continue
                
    def extract_tender_details(self):
        tender_details = {}
        try:
            tender_details['organisation_chain'] = self.driver.find_element(By.XPATH, "//td[b='Organisation Chain']/following-sibling::td/b").text
            tender_details['tender_reference_number'] = self.driver.find_element(By.XPATH, "//td[b='Tender Reference Number']/following-sibling::td/b").text
            tender_details['tender_id'] = self.driver.find_element(By.XPATH, "//td[b='Tender ID']/following-sibling::td/b").text
            tender_details['withdrawal_allowed'] = self.driver.find_element(By.XPATH, "//td[b='Tender ID']/following-sibling::td/following-sibling::td[2]").text
            tender_details['tender_type'] = self.driver.find_element(By.XPATH, "//*[@id='content']/table/tbody/tr[2]/td/table/tbody/tr/td[2]/table/tbody/tr[4]/td/table[2]/tbody/tr/td/table/tbody/tr[2]/td/table/tbody/tr[4]/td[2]").text
            tender_details['form_of_contract'] = self.driver.find_element(By.XPATH, "//*[@id='content']/table/tbody/tr[2]/td/table/tbody/tr/td[2]/table/tbody/tr[4]/td/table[2]/tbody/tr/td/table/tbody/tr[2]/td/table/tbody/tr[4]/td[4]").text
            tender_details['tender_category'] = self.driver.find_element(By.XPATH, "//*[@id='content']/table/tbody/tr[2]/td/table/tbody/tr/td[2]/table/tbody/tr[4]/td/table[2]/tbody/tr/td/table/tbody/tr[2]/td/table/tbody/tr[5]/td[2]").text

            # Tender Fee Details
            tender_details['tender_fee'] = self.driver.find_element(By.XPATH, "//*[@id='content']/table/tbody/tr[2]/td/table/tbody/tr/td[2]/table/tbody/tr[4]/td/table[2]/tbody/tr/td/table/tbody/tr[9]/td/table/tbody/tr/td[1]/table/tbody/tr[2]/td/table/tbody/tr[1]/td[2]").text

            # Work Item Details
            tender_details['title'] = self.driver.find_element(By.XPATH, "//*[@id='content']/table/tbody/tr[2]/td/table/tbody/tr/td[2]/table/tbody/tr[4]/td/table[2]/tbody/tr/td/table/tbody/tr[14]/td/table/tbody/tr[1]/td[2]/b").text
            tender_details['work_description'] = self.driver.find_element(By.XPATH, "//*[@id='content']/table/tbody/tr[2]/td/table/tbody/tr/td[2]/table/tbody/tr[4]/td/table[2]/tbody/tr/td/table/tbody/tr[14]/td/table/tbody/tr[2]/td[2]/b").text
            tender_details['product_category'] = self.driver.find_element(By.XPATH, "//*[@id='content']/table/tbody/tr[2]/td/table/tbody/tr/td[2]/table/tbody/tr[4]/td/table[2]/tbody/tr/td/table/tbody/tr[14]/td/table/tbody/tr[5]/td[4]").text
            tender_details['sub_category'] = self.driver.find_element(By.XPATH, "//*[@id='content']/table/tbody/tr[2]/td/table/tbody/tr/td[2]/table/tbody/tr[4]/td/table[2]/tbody/tr/td/table/tbody/tr[14]/td/table/tbody/tr[5]/td[6]").text
            tender_details['bid_validity_days'] = self.driver.find_element(By.XPATH, "//*[@id='content']/table/tbody/tr[2]/td/table/tbody/tr/td[2]/table/tbody/tr[4]/td/table[2]/tbody/tr/td/table/tbody/tr[14]/td/table/tbody/tr[6]/td[4]").text
            tender_details['period_of_work_days'] = self.driver.find_element(By.XPATH, "//*[@id='content']/table/tbody/tr[2]/td/table/tbody/tr/td[2]/table/tbody/tr[4]/td/table[2]/tbody/tr/td/table/tbody/tr[14]/td/table/tbody/tr[6]/td[6]").text
            tender_details['location'] = self.driver.find_element(By.XPATH, "//*[@id='content']/table/tbody/tr[2]/td/table/tbody/tr/td[2]/table/tbody/tr[4]/td/table[2]/tbody/tr/td/table/tbody/tr[14]/td/table/tbody/tr[7]/td[2]").text
            tender_details['pincode'] = self.driver.find_element(By.XPATH, "//*[@id='content']/table/tbody/tr[2]/td/table/tbody/tr/td[2]/table/tbody/tr[4]/td/table[2]/tbody/tr/td/table/tbody/tr[14]/td/table/tbody/tr[7]/td[4]").text

            # Critical Dates
            tender_details['published_date'] = self.driver.find_element(By.XPATH, "//*[@id='content']/table/tbody/tr[2]/td/table/tbody/tr/td[2]/table/tbody/tr[4]/td/table[2]/tbody/tr/td/table/tbody/tr[17]/td/table/tbody/tr[1]/td[2]").text
            tender_details['bid_opening_date'] = self.driver.find_element(By.XPATH, "//*[@id='content']/table/tbody/tr[2]/td/table/tbody/tr/td[2]/table/tbody/tr[4]/td/table[2]/tbody/tr/td/table/tbody/tr[17]/td/table/tbody/tr[1]/td[4]").text
            tender_details['bid_submission_start_date'] = self.driver.find_element(By.XPATH, "//*[@id='content']/table/tbody/tr[2]/td/table/tbody/tr/td[2]/table/tbody/tr[4]/td/table[2]/tbody/tr/td/table/tbody/tr[17]/td/table/tbody/tr[4]/td[2]").text
            tender_details['bid_submission_end_date'] = self.driver.find_element(By.XPATH, "//*[@id='content']/table/tbody/tr[2]/td/table/tbody/tr/td[2]/table/tbody/tr[4]/td/table[2]/tbody/tr/td/table/tbody/tr[17]/td/table/tbody/tr[4]/td[4]").text
            
            date_keys = ["published_date", "bid_opening_date", "bid_submission_start_date", "bid_submission_end_date"]
            for key in date_keys:
                if key in tender_details:
                    value = tender_details[key]
                    if value != "Not Found":
                        try:
                            date_obj = datetime.strptime(value, "%d-%b-%Y %I:%M %p")
                            tender_details[key] = date_obj
                        except ValueError:
                            print(f"Failed to parse date for {key}: {value}")

            self.tender_details_list.append(tender_details)  # Add details to the list
        except NoSuchElementException as e:
            print(f"Error extracting tender details: {e}")

def scrape_and_insert(keyword):
    tender_automation = TenderAutomation(keyword)
    tender_automation.automate_tender_search()

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


@app.route('/status', methods=['GET'])
def check_status():
    try:
        response = requests.get("https://eprocurentpc.nic.in/nicgep/app?page=FrontEndLatestActiveTenders&service=page", timeout=10)
        if response.status_code == 200:
            return jsonify({"status": "Website is up"})
        else:
            return jsonify({"status": "Website is down"})
    except requests.exceptions.RequestException as e:
        return jsonify({"status": "Website is down", "error": str(e)})
    
if __name__ == '__main__':
    app.run(debug=True)
