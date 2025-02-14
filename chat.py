#####################################
#Chat app for supplier communication#
#Maintainer: Timur Burkhanov       #
#Version: 0.0.1                   #
#Date: 2025-02-11                 #
#####################################

import argparse
import json
import pandas as pd
import smtplib
import logging
import asyncio
import time

from typing import Optional
from openai import OpenAI
from pydantic import BaseModel
from email.mime.text import MIMEText
from telethon.sync import TelegramClient
from telethon.tl.functions.messages import SendMessageRequest
from config import settings

# Configure logging
logging.basicConfig(level=logging.INFO)

# Replace the client initialization
client = OpenAI(api_key=settings.OPENAI_API_KEY)

# Load the JSON data using the json module
with open("data/01_initial_input/dummy_data.json", encoding='utf-8') as json_file:
    data = json.load(json_file)

# Wrap the data in a list to represent a single row and convert to a DataFrame
df = pd.json_normalize(data, record_path=['suppliers'], meta=["parameters", "communication_format", "language", "category"])

def get_telegram_client():
    """Initialize and return Telegram client."""
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    if not settings.TELEGRAM_API_ID or not settings.TELEGRAM_API_HASH:
        logging.warning("Telegram API credentials not set")
        return None

    return TelegramClient('session_name', 
                         settings.TELEGRAM_API_ID, 
                         settings.TELEGRAM_API_HASH,
                         loop=loop)

def get_supplier_data(df, communication_format, language='русский'):
    try:
        # Extract parameters from the DataFrame
        parameters = df.columns.tolist()
        parameters.remove('name')
        parameters.remove('contact')

        # Initialize the DataFrame to store results
        results_df = pd.DataFrame(columns=["Название поставщика", "Контактные данные"] + parameters)
        
        # Iterate over each supplier in the DataFrame
        for index, row in df.iterrows():
            try:
                supplier_data = {
                    "Название поставщика": row['name'],
                    "Контактные данные": row['contact']
                }

                # Send initial message and process response
                send_initial_message(row['contact'], communication_format)
                response_data = receive_and_process_response(row['contact'], communication_format, parameters)

                # Append only the response data
                results_df = pd.concat([results_df, pd.DataFrame([response_data])], ignore_index=True)
                
            except Exception as e:
                logging.error(f"Error processing supplier {row['name']}: {e}")
                continue

        # Save the results DataFrame to Excel
        results_df.to_excel('supplier_data.xlsx', index=False)
        return results_df
        
    except Exception as e:
        logging.error(f"Error in get_supplier_data: {e}")
        raise

def send_initial_message(contact, communication_format):
    message =  '''Добрый день!
            Меня зовут Алексей Смирнов, я менеджер по закупкам компании XYZ. Мы рассматриваем возможность сотрудничества и заинтересованы в вашей продукции.
            Не могли бы вы предоставить информацию по следующим параметрам:

            1. Название товара
            2. Минимальный объем заказа
            3. Цена за единицу
            4. Сроки поставки
            5. Гарантия

            Буду благодарен за быстрый ответ!
                '''
    communicate_with_supplier(contact, message, communication_format)

class SupplierResponse(BaseModel):
    name: Optional[str] = None
    contact: Optional[str] = None
    product_name: Optional[str] = None
    min_order: Optional[str] = None
    unit_price: Optional[str] = None
    delivery_time: Optional[str] = None
    warranty: Optional[str] = None

    @property
    def is_complete(self) -> bool:
        required_fields = ['product_name', 'min_order', 'unit_price', 
                          'delivery_time', 'warranty']
        return all(getattr(self, field) is not None for field in required_fields)

    def missing_fields(self) -> list[str]:
        field_mapping = {
            'product_name': "Название товара",
            'min_order': "Минимальный объем заказа",
            'unit_price': "Цена за единицу",
            'delivery_time': "Сроки поставки",
            'warranty': "Гарантия"
        }
        return [field_mapping[field] for field in field_mapping 
                if getattr(self, field) is None]

def parse_response(response: str, parameters: list[str]) -> SupplierResponse:
    """
    Parse supplier response using OpenAI to extract structured data.
    """
    try:
        system_prompt = """
        You are a data extraction specialist. Extract the following information from the supplier's response:
        - Product name (Название товара)
        - Minimum order quantity (Минимальный объем заказа)
        - Unit price (Цена за единицу)
        - Delivery time (Сроки поставки)
        - Warranty (Гарантия)

        Return the information in a JSON format with these exact Russian keys. 
        If a field is not found in the text, set its value to null.
        Only return the JSON object, nothing else.
        """

        completion = client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": response}
            ]
        )

        # Extract JSON from the response
        response_text = completion.choices[0].message.content.strip()
        try:
            parsed_json = json.loads(response_text)
        except json.JSONDecodeError:
            logging.error(f"Failed to parse JSON from response: {response_text}")
            raise
        
        # Convert to our SupplierResponse model
        supplier_response = SupplierResponse(
            product_name=parsed_json.get("Название товара"),
            min_order=parsed_json.get("Минимальный объем заказа"),
            unit_price=parsed_json.get("Цена за единицу"),
            delivery_time=parsed_json.get("Сроки поставки"),
            warranty=parsed_json.get("Гарантия")
        )

        logging.info(f"Parsed response: {supplier_response.model_dump_json(indent=2)}")
        return supplier_response

    except Exception as e:
        logging.error(f"Error parsing response: {str(e)}")
        raise


def receive_and_process_response(contact: str, communication_format: str, parameters: list[str]) -> dict:
    """
    Receive and process supplier response, following up if needed.
    """
    # Get initial response
    response = wait_for_response(contact, communication_format)
    
    if response is None:
        logging.warning(f"No response received from {contact} after waiting.")
        return {}

    # Parse the response
    supplier_response = parse_response(response, parameters)
    
    # Check if all required fields are present
    if not supplier_response.is_complete:
        missing_fields = supplier_response.missing_fields()
        logging.info(f"Missing fields in response: {missing_fields}")
        
        # Generate and send follow-up message
        follow_up_message = generate_follow_up_message(missing_fields)
        communicate_with_supplier(contact, follow_up_message, communication_format)
        
        # Wait for and process follow-up response
        follow_up_response = wait_for_response(contact, communication_format)
        follow_up_parsed = parse_response(follow_up_response, parameters)
        
        # Merge the responses, taking non-None values from follow-up
        for field, value in follow_up_parsed.model_dump().items():
            if value is not None:
                setattr(supplier_response, field, value)
    
    return supplier_response.model_dump()

def generate_follow_up_message(missing_parameters):
    prompt = f"Пожалуйста, уточните следующую информацию: {', '.join(missing_parameters)}."
    try:
        system_prompt = """
        You are a purchasing manager at XYZ company. Generate a polite follow-up message in Russian 
        asking for missing information from a supplier. Keep the tone professional and friendly.
        """
        
        response = client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt}
            ]
        )
        message_content = response.choices[0].message.content.strip()
        logging.info(f"Generated follow-up message: {message_content}")
        return message_content
    except Exception as e:
        logging.error(f"Error generating follow-up message: {e}")
        raise

def receive_response(contact, communication_format):
    if communication_format == 'email':
        # Use settings instead
        emails = read_emails_from_gmail(settings.GMAIL_USER, 
                                      settings.GMAIL_PASSWORD, 
                                      contact)
        
        # Return the latest email body
        if emails:
            return emails[0]['body']  # Assuming you want the latest email
        else:
            return "No response received from supplier."
    else:
        # Implement logic for other communication formats if needed
        return "Unsupported communication format"

def communicate_with_supplier(contact, message, communication_format):
    if communication_format == 'telegram':
        if contact.startswith('telegram:@'):
            telegram_client = get_telegram_client()
            if telegram_client:
                with telegram_client:
                    telegram_client.send_message(contact, message)
                    logging.info(f"Message sent to {contact} via Telegram.")
                    return "Sample response from supplier"
            else:
                logging.error("Telegram client not initialized")
                return "Telegram client not available"
        else:
            logging.error(f"Invalid Telegram contact: {contact}")
            return "Invalid Telegram contact"
    elif communication_format == 'email':
        send_email(contact, message)
        return "Email sent to supplier"
    else:
        logging.error(f"Unsupported communication format: {communication_format}")
        return "Unsupported communication format"

def send_email(to_address, message):
    msg = MIMEText(message)
    msg['Subject'] = 'Inquiry from XYZ Company'
    msg['From'] = settings.GMAIL_USER
    msg['To'] = to_address

    try:
        with smtplib.SMTP_SSL(settings.SMTP_SERVER, 
                             settings.SMTP_PORT, 
                             timeout=30) as server:
            server.login(settings.GMAIL_USER, settings.GMAIL_PASSWORD)
            server.sendmail(settings.GMAIL_USER, to_address, msg.as_string())
            logging.info(f"Email sent successfully to {to_address}")
    except Exception as e:
        logging.error(f"Failed to send email to {to_address}: {e}")
        raise

def read_emails_from_gmail(user: str, password: str, contact: str) -> list[dict]:
    """Read emails from Gmail for a specific contact."""
    import imaplib
    import email
    from email.header import decode_header
    
    emails = []
    try:
        # Connect to Gmail IMAP server
        imap_server = "imap.gmail.com"
        imap = imaplib.IMAP4_SSL(imap_server)
        imap.login(user, password)
        
        # Select the inbox
        imap.select("INBOX")
        
        # Search for emails from the contact
        _, messages = imap.search(None, f'FROM "{contact}"')
        
        # Get the latest email
        for msg_num in messages[0].split()[-1:]:  # Only get the latest email
            _, msg_data = imap.fetch(msg_num, "(RFC822)")
            email_body = msg_data[0][1]
            email_message = email.message_from_bytes(email_body)
            
            # Get the email body
            body = ""
            if email_message.is_multipart():
                for part in email_message.walk():
                    if part.get_content_type() == "text/plain":
                        body = part.get_payload(decode=True).decode()
                        break
            else:
                body = email_message.get_payload(decode=True).decode()
            
            emails.append({
                'subject': decode_header(email_message["subject"])[0][0],
                'from': email_message["from"],
                'body': body
            })
        
        imap.close()
        imap.logout()
        return emails
        
    except Exception as e:
        logging.error(f"Error reading emails: {e}")
        return []

def wait_for_response(contact, communication_format, timeout=300, interval=30):
    """
    Wait for a response from the supplier, checking periodically.
    """
    start_time = time.time()
    while time.time() - start_time < timeout:
        response = receive_response(contact, communication_format)
        if response != "No response received from supplier.":
            return response
        logging.info("No response yet, waiting...")
        time.sleep(interval)
    logging.warning("Timeout reached without receiving a response.")
    return None

def main():
    # Set up argument parser
    parser = argparse.ArgumentParser(description='Process supplier data.')
    parser.add_argument('--communication_format', type=str, default='email', help='Communication format (e.g., email, telegram)')

    # Parse arguments
    args = parser.parse_args()

    # Call the function with the parsed argument
    get_supplier_data(df, args.communication_format)

if __name__ == "__main__":
    main()

print(df.to_string())