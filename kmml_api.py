# -*- coding: utf-8 -*-

import requests
from bs4 import BeautifulSoup
import json
from pymongo import MongoClient
from flask import Flask, jsonify, request
from datetime import datetime

class TenderScraper:
    def __init__(self, mongo_uri, db_name):
        try:
            self.client = MongoClient(mongo_uri)
            self.db = self.client[db_name]
            print("Connected to MongoDB successfully.")
        except Exception as e:
            print(f"Error connecting to MongoDB: {e}")

    def fetch_tender_info(self, url):
        try:
            # Fetch the HTML content from the given URL
            response = requests.get(url)
            response.raise_for_status()  # Raise an error if the request was unsuccessful
            html_content = response.content

            # Parse the HTML content using BeautifulSoup
            soup = BeautifulSoup(html_content, 'html.parser')

            # Initialize a list to store the tender information
            tenders = []

            # Find all tender divs
            tender_divs = soup.find_all('div', class_='tenderdivRow')

            # Extract tender information from each tender div
            for tender_div in tender_divs:
                serial_no = tender_div.find('label', string='Serial No:').find_next_sibling(string=True).strip()
                description = tender_div.find('label', string='Description').find_next_sibling(string=True).strip()
                posted_date_time_str = tender_div.find('label', string='Posted Date & time').find_next_sibling(string=True).strip()
                last_date_time_str = tender_div.find('label', string='Last Date & Time').find_next_sibling(string=True).strip()

                # Convert date strings to datetime objects
                posted_date_time = datetime.strptime(posted_date_time_str, "%d-%m-%Y, %I:%M%p")
                last_date_time = datetime.strptime(last_date_time_str, "%d-%m-%Y, %I:%M%p")

                days_remaining = ''.join([span.text for span in tender_div.find_all('span')])
                link_suffix = tender_div.find('a', string='More')['href']
                link = f"https://www.kmml.com{link_suffix}"

                # Create a dictionary with the tender information
                tender = {
                    "serial_no": serial_no,
                    "description": description,
                    "posted_date_time": posted_date_time,
                    "last_date_time": last_date_time,
                    "days_remaining": days_remaining,
                    "link": link
                }

                # Add the tender information to the list
                tenders.append(tender)

            # Save to MongoDB
            self.save_to_mongodb(tenders)

            # Create the output dictionary
            output = {
                "title": "Tenders and Enquiries at KMML",
                "content": tenders
            }

            return output
        except Exception as e:
            print(f"Error fetching tender info: {e}")
            raise e

    def save_to_mongodb(self, tenders):
        try:
            collection = self.db["kmml_tenders"]  # Use the desired collection name
            for details in tenders:
                existing_tender = collection.find_one({"serial_no": details.get("serial_no")})
                if existing_tender:
                    print(f"Tender with Serial No {details.get('serial_no')} already exists. Skipping...")
                else:
                    collection.insert_one(details)
                    print(f"Tender with Serial No {details.get('serial_no')} added to the database.")
            print("All tenders saved to MongoDB successfully")
        except Exception as e:
            print(f"Error saving to MongoDB: {e}")
            raise e

    def get_tenders(self, query=None):
        try:
            collection = self.db["kmml_tenders"]
            if query:
                tenders = collection.find({"description": {"$regex": query, "$options": "i"}})
            else:
                tenders = collection.find()
            return list(tenders)
        except Exception as e:
            print(f"Error getting tenders: {e}")
            raise e

# Flask app
app = Flask(__name__)

# MongoDB connection details
mongo_uri = "mongodb+srv://arun:94u4vK58Mei1VSGS@cluster0.m50mnij.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0"
db_name = 'tender_database'
scraper = TenderScraper(mongo_uri, db_name)

@app.route('/')
def status():
    return jsonify({"status": "API is running"}), 200

@app.route('/fetch-tenders', methods=['GET'])
def fetch_tenders():
    # URL to scrape
    url = 'https://www.kmml.com/open-tender'
    try:
        output = scraper.fetch_tender_info(url)
        return jsonify(output), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/search-tenders', methods=['GET'])
def search_tenders():
    query = request.args.get('query')
    try:
        tenders = scraper.get_tenders(query)
        return jsonify(tenders), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run()