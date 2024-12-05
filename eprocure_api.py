from flask import Flask, jsonify, request
import threading
import unittest
import requests
from random import uniform
from time import sleep
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import NoSuchElementException, TimeoutException, NoSuchWindowException
import easyocr
import numpy as np
import csv
import cv2
import os
from datetime import datetime
from PIL import Image
from io import BytesIO
import logging
import warnings
import pymongo

app = Flask(__name__)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logging.getLogger('urllib3').setLevel(logging.ERROR)
warnings.filterwarnings('ignore', 'Unverified HTTPS request')
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '2'

class TenderCaptchaSolver(unittest.TestCase):

    def __init__(self, website_link, keyword, thread_finished):
        self.website_link = website_link
        self.keyword = keyword
        self.thread_finished = thread_finished  # Event to signal thread finished
        options = webdriver.ChromeOptions()
        options.add_argument('--headless')
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        self.driver = webdriver.Chrome(options=options)
        self.driver.get(self.website_link)
        self._stop_signal = threading.Event()
        # MongoDB connection
        self.client = pymongo.MongoClient("mongodb+srv://arun:94u4vK58Mei1VSGS@cluster0.m50mnij.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0")
        self.db = self.client["tender_database"]
        self.collection = self.db[f"eprocure_{self.keyword}"]  # Use keyword to set the collection name
        print("Value:", self.keyword)
        print("Param:", f"eprocure_{self.keyword}")

    # Preprocess image function
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

    # EasyOCR function
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
            EC.presence_of_element_located((By.CSS_SELECTOR, "img[data-drupal-selector='edit-captcha-image']"))
        )
        captcha_src = captcha_image.get_attribute('src')
        image_format = 'png' if '.png' in captcha_src.lower() else 'jpg'

        captcha_folder = 'C:/Users/kvaru/Eprocure_Tender/captcha_images'
        os.makedirs(captcha_folder, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        captcha_image_path = os.path.join(captcha_folder, f'captcha_{timestamp}.{image_format}')

        if captcha_src.startswith('http'):
            response = requests.get(captcha_src)
            image = Image.open(BytesIO(response.content))
            image.save(captcha_image_path)
        else:
            captcha_image.screenshot(captcha_image_path)

        preprocessed_folder = 'C:/Users/kvaru/Eprocure_Tender/pre_processed_captchas'
        os.makedirs(preprocessed_folder, exist_ok=True)
        preprocessed_image_path = self.preprocess_image(captcha_image_path, 50, 200, preprocessed_folder, debug=True)
        captcha_text = self.easy_ocr_captcha(preprocessed_image_path)

        print("Captcha Text:", captcha_text)  # Print the captcha text for debugging
        return captcha_text

    def extract_tender_details(self):
        # New method to extract tender details
        tender_details = {}
        tender_details.update(self.extract_tender_section_details("//div[@id='tender_full_view']/div/table[1]"))
        tender_details.update(self.extract_tender_section_details("//div[@id='tender_full_view']/div/table[2]"))
        tender_details.update(self.extract_tender_section_details("//div[@id='tender_full_view']/div/table[3]"))
        return tender_details

    def extract_tender_section_details(self, section_xpath):
        # Helper method to extract tender details from a section
        section = self.driver.find_element(By.XPATH, section_xpath)
        detail_elements = section.find_elements(By.XPATH, ".//div[contains(@class, 'black')]")
        details = {}
        for element in detail_elements:
            key, value = [x.strip() for x in element.text.split(':', 1)]
            details[key] = value
        return details

    def is_captcha_solved(self):
        # Check for the presence of a captcha error message
        error_message_elements = self.driver.find_elements(By.XPATH, "//div[contains(@role, 'alert')]")
        if len(error_message_elements) > 0:
            # If an error message is found, the captcha was not solved
            print("Captcha error message detected, captcha not solved.")
            return False
        # No error message, we can assume the captcha was solved
        return True

    def handle_error(self, error):
        error_message = f"An error occurred: {str(error)}"
        print(error_message)  # For logging
        return error_message  # This will be used by Streamlit

    def extract_organisation_details(self):
        WebDriverWait(self.driver, 10).until(
            EC.visibility_of_element_located((By.XPATH, "//div[@id='tender_full_view']//table"))
        )

        details = {}
        detail_rows = self.driver.find_elements(
            By.XPATH, "//div[@id='tender_full_view']//table//tr"
        )

        key_mapping = {
            "Organisation Name": "organisation_name",
            "Organisation Type": "organisation_type",
            "Tender Title": "tender_title",
            "Tender Reference Number": "tender_reference_number",
            "Tender Category": "tender_category",
            "Product Sub-Category": "product_sub_category",
            "EMD": "emd",
            "ePublished Date": "epublished_date",
            "Document Download Start Date": "document_download_start_date",
            "Bid Submission Start Date": "bid_submission_start_date",
            "Work Description": "work_description",
            "Tender Document": "tender_document",
            "Name": "name",
            "Address": "address",
            "Tender Type": "tender_type",
            "Product Category": "product_category",
            "Tender Fee": "tender_fee",
            "Location": "location",
            "Bid Submission End Date": "bid_submission_end_date"
        }

        for row in detail_rows:
            header_elements = row.find_elements(
                By.XPATH, ".//td[contains(@class, 'black') and contains(@class, 'border-top-none')]"
            )

            if not header_elements:
                header_elements = row.find_elements(By.XPATH, ".//td[contains(@class, 'black')]")

            if header_elements:
                header = header_elements[0].text.strip(': ').strip()
                key = key_mapping.get(header, header)  # Map the key if a mapping exists

                value_cell = header_elements[0].find_elements(By.XPATH, "./following-sibling::td[@width='20%']")
                if not value_cell:
                    value_cell = header_elements[0].find_elements(By.XPATH, "./following-sibling::td[not(contains(@class, 'black'))]")

                if value_cell:
                    value = value_cell[0].text.strip().replace(u'\xa0', u' ')
                    details[key] = value if value else "Not Found"
                else:
                    details[key] = "Not Found"
            else:
                continue

        # Extract additional fields
        additional_fields = {
            "tender_type": "//td[contains(text(),'Tender Type')]/following-sibling::td[@width='20%']",
            "product_category": "//td[contains(text(),'Product Category')]/following-sibling::td[@width='20%']",
            "tender_fee": "//td[contains(text(),'Tender Fee')]/following-sibling::td[@width='20%']",
            "location": "//td[contains(text(),'Location')]/following-sibling::td[@width='20%']"
        }

        for field, xpath in additional_fields.items():
            try:
                element = self.driver.find_element(By.XPATH, xpath)
                details[field] = element.text.strip().replace(u'\xa0', u' ') if element.text.strip() else "Not Found"
            except NoSuchElementException:
                details[field] = "Not Found"

        bid_submission_start_date_element = self.driver.find_element(By.XPATH, "//td[contains(text(),'Bid Submission Start Date')]/following-sibling::td[@width='20%']")
        bid_submission_start_date = bid_submission_start_date_element.text.strip().replace(u'\xa0', u' ')
        details['bid_submission_start_date'] = bid_submission_start_date if bid_submission_start_date else "Not Found"

        bid_submission_end_date_element = self.driver.find_element(By.XPATH, "//td[contains(text(),'Bid Submission End Date')]/following-sibling::td[@width='20%']")
        bid_submission_end_date = bid_submission_end_date_element.text.strip().replace(u'\xa0', u' ')
        details['bid_submission_end_Date'] = bid_submission_end_date if bid_submission_end_date else "Not Found"

        date_keys = ["epublished_date", "document_download_start_date", "bid_submission_start_date", "bid_submission_end_Date"]
        for key in date_keys:
            if key in details:
                 value = details[key]
                 if value != "Not Found":
                    try:
                        date_obj = datetime.strptime(value, "%d-%b-%Y %I:%M %p")
                        details[key] = date_obj
                    except ValueError:
                        print(f"Failed to parse date for {key}: {value}")

        print("Extracted details:")
        for key, value in details.items():
            print(f"{key}: {value}")

        return details

    def save_to_mongodb(self, details):
        existing_tender = self.collection.find_one({"Tender Reference Number": details.get("Tender Reference Number")})

        if existing_tender:
            print(f"Tender with Reference Number {details.get('Tender Reference Number')} already exists. Skipping...")
        else:
            self.collection.insert_one(details)
            print(f"Tender with Reference Number {details.get('Tender Reference Number')} added to the database.")
            print("Tender Details saved to Mongo successfully")

    def search_tenders(self):
        max_attempts = 15
        for attempt in range(max_attempts):
            keyword_input = WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.ID, 'skeyword'))
            )
            keyword_input.clear()
            keyword_input.send_keys(self.keyword)

            captcha_text = self.solve_captcha()

            captcha_response_input = WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, 'input[data-drupal-selector="edit-captcha-response"]'))
            )
            captcha_response_input.clear()
            captcha_response_input.send_keys(captcha_text)

            search_button = self.driver.find_element(By.ID, 'btnSearch')
            search_button.click()

            sleep(3)

            if self.driver.find_elements(By.CSS_SELECTOR, '.messages--error'):
                logging.info(f"Captcha failed on attempt {attempt + 1}. Retrying...")
                self.driver.back()
                WebDriverWait(self.driver, 10).until(
                    EC.presence_of_element_located((By.ID, 'skeyword'))
                )
            elif self.driver.find_elements(By.XPATH, "//table[contains(@class, 'list_table')]"):
                logging.info("Captcha solved successfully, search submitted.")
                return True
            else:
                logging.error("Unexpected page layout after captcha submission.")
                return False

        logging.error("Failed to solve captcha after maximum attempts.")
        return False

    def run(self):
        while not self._stop_signal.is_set():
            try:
                if not self.search_tenders():
                    continue

                for i in range(10):  # Check only the first 10 tenders
                    if self.thread_finished.is_set():  # Check if the thread has finished its task
                        break  # If thread has finished, exit loop

                    WebDriverWait(self.driver, 10).until(
                        EC.visibility_of_element_located((By.XPATH, "//table[contains(@class, 'list_table')]"))
                    )

                    tender_links = self.driver.find_elements(
                        By.XPATH, "//table[contains(@class, 'list_table')]//tr/td[5]/a"
                    )
                    tender_links[i].click()

                    max_attempts = 10
                    for attempt in range(1, max_attempts + 1):
                        captcha_solution = self.solve_captcha()
                        print(f"Attempt {attempt}: Captcha Text: {captcha_solution}")

                        captcha_input = WebDriverWait(self.driver, 10).until(
                            EC.presence_of_element_located((By.ID, 'edit-captcha-response'))
                        )
                        captcha_input.clear()
                        captcha_input.send_keys(captcha_solution)

                        submit_button = self.driver.find_element(By.ID, 'edit-save')
                        submit_button.click()

                        sleep(5)

                        if self.is_captcha_solved():
                            organisation_details = self.extract_organisation_details()

                            self.save_to_mongodb(organisation_details)
                            
                            break
                        else:
                            print("Failed to solve captcha, retrying...")

                    self.driver.back()
                    sleep(3)

                    self.driver.get(self.website_link)
                    self.search_tenders()

                if self._stop_signal.is_set():
                    self.stop()
                    break
            except TimeoutException as e:
                print(f"Timed out waiting for page elements: {e}")
            except IndexError:
                return "The sector you have looked has no tender currently."
            except NoSuchWindowException:
                return "User closed the window or the window was terminated."
            except Exception as e:
                return self.handle_error(e)

    def stop(self):
        self._stop_signal.set()
        self.driver.quit()

# Flask routes

@app.route('/status', methods=['GET'])
def scraper_status():
    try:
        keyword = request.args.get("keyword")
        website_link = "https://eprocure.gov.in/cppp/latestactivetendersnew/cpppdata"
        solver = TenderCaptchaSolver(website_link, keyword, threading.Event())
        if solver._stop_signal.is_set():
            return jsonify({"status": "stopped"}), 200
        else:
            return jsonify({"status": "running"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/search', methods=['GET'])
def start_search():
    try:
        keywords = request.args.get("keywords")
        website_link = "https://eprocure.gov.in/cppp/latestactivetendersnew/cpppdata"
        keywords_list = keywords.split(',')  # Split keywords by comma
        threads = []
        thread_finished = threading.Event()  # Event to signal thread finished
        for keyword in keywords_list:
            solver = TenderCaptchaSolver(website_link, keyword, thread_finished)
            thread = threading.Thread(target=solver.run)
            threads.append(thread)
            thread.start()

        for thread in threads:
            thread.join()

        return jsonify({"message": "Search completed successfully."}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/stop', methods=['GET'])
def stop_search():
    try:
        keyword = request.args.get("keyword")
        website_link = "https://eprocure.gov.in/cppp/latestactivetendersnew/cpppdata"
        solver = TenderCaptchaSolver(website_link, keyword, threading.Event())
        solver.stop()
        return jsonify({"message": "Search stopped successfully."}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
   app.run(host=os.environ.get('HOST', '0.0.0.0'), port=5000)
