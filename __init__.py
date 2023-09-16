import os
import requests
import json
import mysql.connector
from dotenv import load_dotenv
import logging
from datetime import datetime
import traceback
from azure.functions import HttpRequest, HttpResponse

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment variables from the .env file
load_dotenv()

apiDate = datetime.now().strftime("%Y-%m-%d")
displayDate = datetime.now().strftime("%d-%b-%Y")

from decouple import config

# External API URLs
INVESTWELL_API_URL = config("INVESTWELL_API_URL")
WATI_API_URL = config("WATI_API_URL")

# API Keys
INVESTWELL_AUTH_NAME = config("INVESTWELL_AUTH_NAME")
INVESTWELL_AUTH_PASSWORD = config("INVESTWELL_AUTH_PASSWORD")
WATI_BEARER_TOKEN = config("WATI_BEARER_TOKEN")

# Database Details
DB_HOST = config("DB_HOST")
DB_USER = config("DB_USER")
DB_PASSWORD = config("DB_PASSWORD")
DB_DATABASE = config("DB_DATABASE")

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Establish a database connection
connection = mysql.connector.connect(
    host=DB_HOST, user=DB_USER, password=DB_PASSWORD, database=DB_DATABASE
)


def fetch_details_from_waid(waid):
    connection = None
    cursor = None
    details = None

    try:
        connection = mysql.connector.connect(
            host=DB_HOST,
            user=DB_USER,
            password=DB_PASSWORD,
            database=DB_DATABASE,
        )
        cursor = connection.cursor(dictionary=True)
        query = "SELECT * FROM pan_fetch WHERE waid = %s"
        cursor.execute(query, (waid,))
        details = cursor.fetchone()
        if not details:
            logger.error(f"No details found for waid {waid}.")
            return None

    except mysql.connector.Error as err:
        logger.error(
            f"Database error while fetching details for waid {waid}. Error: {err}"
        )
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

    return details


def get_investwell_token():
    url = f"{INVESTWELL_API_URL}/auth/getAuthorizationToken"
    payload = json.dumps(
        {"authName": INVESTWELL_AUTH_NAME, "password": INVESTWELL_AUTH_PASSWORD}
    )
    headers = {"Content-Type": "application/json"}
    response = requests.post(url, headers=headers, data=payload)
    data = response.json()
    token = data.get("result").get("token")
    return token


def main(req: HttpRequest) -> HttpResponse:
    try:
        if req.method == "GET":
            # Respond with "Hello, World!" for GET requests
            return HttpResponse("Hello, World!", status_code=200)

        data = req.get_json()
        waid = data.get("waid")

        details = fetch_details_from_waid(waid)
        if not details:
            return HttpResponse(
                json.dumps({"error": "Invalid WAID or database error"}), status_code=400
            )
        pan = details["pan"]
        name = details["name"]

        token = get_investwell_token()
        if not token:
            return HttpResponse(
                json.dumps({"error": "Failed to obtain InvestWell token"}),
                status_code=500,
            )

        pdf_url = f"{INVESTWELL_API_URL}/reports/getPortfolioReport?filters=[{{%22endDate%22:%22{apiDate}%22,%22dataSource%22:%220%22,%22pan%22:%22{pan}%22}}]&token={token}"

        response = requests.get(pdf_url)
        if response.status_code == 200:
            pdf_data = response.content

            url = f"{WATI_API_URL}/api/v1/sendSessionFile/{waid}"
            headers = {"Authorization": WATI_BEARER_TOKEN}
            files = {"file": ("Report.pdf", pdf_data, "application/pdf")}
            pdf_response = requests.post(url, files=files, headers=headers)

            if pdf_response.status_code == 200:
                url = f"{WATI_API_URL}/api/v1/sendInteractiveButtonsMessage?whatsappNumber={waid}"
                headers = {
                    "Content-Type": "application/json",
                    "Authorization": WATI_BEARER_TOKEN,
                }
                payload = {
                    "body": f"Dear {name}, \n\nHere's your Portfolio Valuation Report as on {displayDate}.",
                    "buttons": [{"text": "Send on mail"}],
                    "footer": "mNivesh Team",
                }
                msg_response = requests.post(url, json=payload, headers=headers)
                if msg_response.status_code != 200:
                    logger.error(
                        f"Failed to send follow-up message. Status Code: {msg_response.status_code}, Response: {msg_response.text}"
                    )
                    return HttpResponse(
                        json.dumps(
                            {
                                "error": f"Failed to send message. Response: {msg_response.text}"
                            }
                        ),
                        status_code=500,
                    )
            else:
                return HttpResponse(
                    json.dumps({"error": "Failed to send PDF"}), status_code=500
                )

            return HttpResponse(
                json.dumps({"message": "Report and message sent successfully"}),
                status_code=200,
            )

    except Exception as e:
        logger.error(f"An error occurred: {str(e)}")
        traceback.print_exc()
        return HttpResponse(
            json.dumps({"error": "Internal server error"}), status_code=500
        )
    finally:
        # Close the database connection
        if connection:
            connection.close()
