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
from email.mime.text import MIMEText
import logging
import openai

from telethon.sync import TelegramClient
from telethon.tl.functions.messages import SendMessageRequest

# Configure logging
logging.basicConfig(level=logging.INFO)

# client = OpenAI(api_key="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")
client = OpenAI()
# Load the JSON data using the json module
with open("data/01_initial_input/dummy_data.json", encoding='utf-8') as json_file:
    data = json.load(json_file)

# Wrap the data in a list to represent a single row and convert to a DataFrame
df = pd.json_normalize(data, record_path=['suppliers'], meta=["parameters", "communication_format", "language", "category"])
# Initialize Telegram Client
api_id = '20451134'  # Replace with your actual API ID
api_hash = 'f3d0adaf42f72131c6d1df004eb9122b'  # Replace with your actual API Hash
telegram_client = TelegramClient('session_name', api_id, api_hash)


def get_supplier_data(df, communication_format, language='русский'):
    # Extract parameters from the DataFrame
    parameters = df.columns.tolist()
    parameters.remove('name')
    parameters.remove('contact')

    # Initialize the DataFrame to store results
    results_df = pd.DataFrame(columns=["Название поставщика", "Контактные данные"] + parameters)
    
    # Iterate over each supplier in the DataFrame
    for index, row in df.iterrows():
        supplier_data = {
            "Название поставщика": row['name'],
            "Контактные данные": row['contact']
        }

        # Send initial message
        send_initial_message(row['contact'], communication_format)

        # Receive and process response
        response_data = receive_and_process_response(row['contact'], communication_format, parameters)

        # Append the supplier data to the results DataFrame using pd.concat
        results_df = pd.concat([results_df, pd.DataFrame([{**supplier_data, **response_data}])], ignore_index=True)

    # Save the results DataFrame to Excel
    results_df.to_excel('supplier_data.xlsx', index=False)

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

def receive_and_process_response(contact, communication_format, parameters):
    # Placeholder for receiving a response
    response = receive_response(contact, communication_format)
    
    # Parse the response
    parsed_data = parse_response(response, parameters)
    
    # Check if all parameters are filled
    missing_parameters = [param for param in parameters if param not in parsed_data or not parsed_data[param]]
    
    if missing_parameters:
        # Generate follow-up questions using OpenAI
        follow_up_message = generate_follow_up_message(missing_parameters)
        communicate_with_supplier(contact, follow_up_message, communication_format)
        # Recursively process the new response
        return receive_and_process_response(contact, communication_format, parameters)
    
    return parsed_data

def generate_follow_up_message(missing_parameters):
    prompt = f"Пожалуйста, уточните следующую информацию: {', '.join(missing_parameters)}."
    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": 
                 '''Ты — менеджер по закупкам компании XYZ, который получает ответы от поставщиков 
                 продукции, которую они могут предложить. 
                 Ты должен быть вежливым и профессиональным.'''},
                {"role": "user", "content": prompt}
            ]
        )
        message_content = response.choices[0].message['content'].strip()
        logging.info(f"Generated follow-up message: {message_content}")
        return message_content
    except Exception as e:
        logging.error(f"Error generating follow-up message: {e}")
        return "An error occurred while generating the message."

def parse_response(response, parameters):
    # Implement parsing logic to extract information from the response
    return {param: "Extracted value" for param in parameters}

def receive_response(contact, communication_format):
    # Implement logic to receive a response from the supplier
    return "Sample response from supplier"

def communicate_with_supplier(contact, message, communication_format):
    if communication_format == 'telegram':
        if contact.startswith('telegram:@'):
            with telegram_client:
                # Send the message to the supplier
                telegram_client.send_message(contact, message)
                print(f"Message sent to {contact} via Telegram.")
                # For simplicity, return a placeholder response
                return "Sample response from supplier"
        else:
            print(f"Invalid Telegram contact: {contact}")
            return "Invalid Telegram contact"
    elif communication_format == 'email':
        # Send an email
        send_email(contact, message)
        return "Email sent to supplier"
    else:
        print(f"Unsupported communication format: {communication_format}")
        return "Unsupported communication format"

def send_email(to_address, message):
    # Set up the server
    smtp_server = 'smtp.gmail.com'  # Replace with your SMTP server
    smtp_port = 465  # Replace with your SMTP port
    smtp_user = 'snapikk@gmail.com'  # Replace with your email
    smtp_password = 'vlpu hjbm qwrl jlze'  # Replace with your email password

    # Create the email
    msg = MIMEText(message)
    msg['Subject'] = 'Inquiry from XYZ Company'
    msg['From'] = smtp_user
    msg['To'] = to_address

    # Send the email
    try:
        with smtplib.SMTP_SSL(smtp_server, smtp_port, timeout=30) as server:  # Increased timeout
            server.login(smtp_user, smtp_password)
            server.sendmail(smtp_user, to_address, msg.as_string())
            print(f"Email sent to {to_address}")
    except Exception as e:
        print(f"Failed to send email: {e}")

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

print(df)