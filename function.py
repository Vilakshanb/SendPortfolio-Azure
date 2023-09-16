from flask import Flask, request, jsonify
import requests
import os
import json
import mysql.connector
from dotenv import load_dotenv
import logging
from datetime import datetime
import traceback

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# Load environment variables from the .env file
load_dotenv()

apiDate = datetime.now().strftime(
    "%Y-%m-%d"
)  # This format may need to be adjusted based on the InvestWell API requirements.
displayDate = datetime.now().strftime(
    "%d-%b-%Y"
)  # This will give the date in the format "dd-mmm-yyyy" for display.


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


# The function to fetch name and pan based on waid
import mysql.connector


def fetch_details_from_waid(waid):
    connection = None
    cursor = None
    details = None

    try:
        # Establishing the connection
        connection = mysql.connector.connect(
            host=DB_HOST,
            user=DB_USER,
            password=DB_PASSWORD,
            database=DB_DATABASE,
        )

        # Creating a cursor and executing the query
        cursor = connection.cursor(
            dictionary=True
        )  # dictionary=True will return results as dictionaries
        query = "SELECT * FROM pan_fetch WHERE waid = %s"
        cursor.execute(query, (waid,))

        # Fetching the results
        details = cursor.fetchone()
        if not details:
            logger.error(f"No details found for waid {waid}.")
            return None

    except mysql.connector.Error as err:
        logger.error(
            f"Database error while fetching details for waid {waid}. Error: {err}"
        )
    finally:
        # Ensure resources are closed
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


app = Flask(__name__)


# ...


@app.route("/")
def root_Process():
    return "Hello World!"


@app.route("/sendReport", methods=["POST"])
def send_report():
    try:
        data = request.get_json()
        waid = data.get("waid")

        # Fetch the name and pan for the given waid
        details = fetch_details_from_waid(waid)
        if not details:
            return jsonify({"error": "Invalid WAID or database error."}), 400
        pan = details["pan"]
        name = details["name"]

        token = get_investwell_token()
        if not token:
            return jsonify({"error": "Failed to obtain InvestWell token"}), 500

        # Construct the dynamic filename using PAN and waid
        filename = f"{pan}_{waid}.pdf"
        pdf_url = f"{INVESTWELL_API_URL}/reports/getPortfolioReport?filters=[{{%22endDate%22:%22{apiDate}%22,%22dataSource%22:%220%22,%22pan%22:%22{pan}%22}}]&token={token}"

        response = requests.get(pdf_url)
        if response.status_code == 200:
            pdf_data = response.content

            # Save the file with the dynamic name
            with open(filename, "wb") as pdf_file:
                pdf_file.write(pdf_data)

            # Send the saved PDF file with the dynamic name
            url = f"{WATI_API_URL}/api/v1/sendSessionFile/{waid}"
            headers = {"Authorization": WATI_BEARER_TOKEN}

            with open(filename, "rb") as pdf_file:
                files = {"file": (filename, pdf_file, "application/pdf")}
                pdf_response = requests.post(url, files=files, headers=headers)

            # If the PDF was sent successfully, send the interactive button message
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

                # Check if interactive message sending was successful
                if msg_response.status_code != 200:
                    logger.error(
                        f"Failed to send follow-up message. Status Code: {msg_response.status_code}, Response: {msg_response.text}"
                    )
                    return (
                        jsonify(
                            {
                                "error": f"Failed to send message. Response: {msg_response.text}"
                            }
                        ),
                        500,
                    )
            else:
                return jsonify({"error": "Failed to send PDF"}), 500

            return jsonify({"message": "Report and message sent successfully"}), 200

    except Exception as e:
        # Log any unhandled exceptions
        logger.error(f"An error occurred: {str(e)}")
        traceback.print_exc()  # Print the stack trace for debugging
        return jsonify({"error": "Internal server error"}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8181, debug=False)  # Set debug to False in production
