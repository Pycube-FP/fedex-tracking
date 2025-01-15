from flask import Flask, jsonify, render_template, request, redirect, url_for, session, flash
import boto3
import logging
from collections import defaultdict
from datetime import datetime
from functools import wraps
import os
from dotenv import load_dotenv
load_dotenv()  # Load environment variables from .env file

app = Flask('FedEx Tracking')
app.secret_key = os.getenv('FLASK_SECRET_KEY', os.urandom(24))

# Initialize a session using Amazon DynamoDB
boto3_session = boto3.Session(
    aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
    aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY'),
    region_name=os.getenv('AWS_REGION')
)

# Create DynamoDB resource
dynamodb = boto3_session.resource('dynamodb')
table = dynamodb.Table('fedexevents')
logging.basicConfig(level=logging.INFO)

# Hardcoded users for demo (in production, use a database and hash passwords)
USERS = {
    'admin': 'admin123',
    'user': 'user123'
}

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'username' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        if username in USERS and USERS[username] == password:
            session['username'] = username
            return redirect(url_for('index'))
        else:
            return render_template('login.html', error='Invalid username or password')
    
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()  # Use Flask's session
    return redirect(url_for('login'))

def process_shipment_data():
    try:
        # Get all shipments in a single scan
        response = table.scan()
        all_events = response['Items']
        
        while 'LastEvaluatedKey' in response:
            response = table.scan(ExclusiveStartKey=response['LastEvaluatedKey'])
            all_events.extend(response['Items'])

        # Initialize data structures
        daily_counts = defaultdict(int)
        status_counts = defaultdict(int)
        lab_counts = defaultdict(int)
        courier_counts = defaultdict(int)
        events_by_tracking = {}

        # First pass - group events by tracking number and count daily shipments
        for event in all_events:
            tracking_number = event['trackingNumber']
            if tracking_number not in events_by_tracking:
                events_by_tracking[tracking_number] = []
                # Count new shipments by date
                date = datetime.strptime(event['eventCreateTime'], '%Y-%m-%dT%H:%M:%S%z').strftime('%Y-%m-%d')
                daily_counts[date] += 1
            events_by_tracking[tracking_number].append(event)

        # Second pass - process status, lab, and courier data
        for tracking_number, events in events_by_tracking.items():
            # Sort events by timestamp
            events.sort(key=lambda x: x['eventCreateTime'])
            latest_event = events[-1]
            
            # Determine final status
            status = 'Shipment Created'
            for event in events:
                desc = event.get('eventDescription', '').strip()
                if 'Shipment Cancelled' in desc:
                    status = 'Cancelled'
                    break
                elif desc == 'Delivered':
                    status = 'Delivered'
                elif 'Delay' in desc:
                    status = 'Delayed'
                elif 'Out for Delivery' in desc or 'In Transit' in desc:
                    status = 'In Transit'

            # Count status
            status_counts[status] += 1
            
            # Count labs and couriers
            lab = latest_event.get('RI_company', 'Unknown')
            courier = latest_event.get('courierType', 'Unknown')
            lab_counts[lab] += 1
            courier_counts[courier] += 1

        # Prepare dates and counts arrays
        dates = sorted(daily_counts.keys())
        counts = [daily_counts[date] for date in dates]

        # Prepare chart data
        status_data = {
            'labels': list(status_counts.keys()),
            'values': list(status_counts.values())
        }

        lab_data = {
            'labels': list(lab_counts.keys()),
            'values': list(lab_counts.values())
        }

        courier_data = {
            'labels': list(courier_counts.keys()),
            'values': list(courier_counts.values())
        }

        return {
            'dates': dates,
            'counts': counts,
            'status_data': status_data,
            'lab_data': lab_data,
            'courier_data': courier_data
        }

    except Exception as e:
        logging.error(f"Error processing shipment data: {e}")
        return {
            'dates': [],
            'counts': [],
            'status_data': {'labels': [], 'values': []},
            'lab_data': {'labels': [], 'values': []},
            'courier_data': {'labels': [], 'values': []}
        }

def get_tracking_timeline(tracking_number):
    try:
        # Get all events for this tracking number
        response = table.scan(
            FilterExpression='trackingNumber = :tn',
            ExpressionAttributeValues={':tn': tracking_number}
        )
        events = response['Items']
        
        # Continue scanning if we have more items
        while 'LastEvaluatedKey' in response:
            response = table.scan(
                FilterExpression='trackingNumber = :tn',
                ExpressionAttributeValues={':tn': tracking_number},
                ExclusiveStartKey=response['LastEvaluatedKey']
            )
            events.extend(response['Items'])

        # Sort events by timestamp
        events.sort(key=lambda x: x['eventCreateTime'])
        
        # Check if shipment is cancelled
        for event in events:
            if 'Shipment Cancelled' in event.get('eventDescription', ''):
                return {
                    'Shipment Cancelled': {
                        'completed': True,
                        'timestamp': event['eventCreateTime']
                    }
                }
        
        # If not cancelled, process normal timeline
        timeline = {
            'Shipment Created': {'completed': False, 'timestamp': None},
            'Shipment Picked Up': {'completed': False, 'timestamp': None},
            'In Transit': {'completed': False, 'timestamp': None},
            'Out For Delivery': {'completed': False, 'timestamp': None},
            'Delivered': {'completed': False, 'timestamp': None}
        }
        
        # First pass - find the earliest In Transit event
        in_transit_time = None
        for event in events:
            desc = event.get('eventDescription', '')
            if ('Departed' in desc or 'Arrived' in desc):
                in_transit_time = event['eventCreateTime']
                break
        
        # Process each event
        for event in events:
            desc = event.get('eventDescription', '')
            
            # Check Shipment Created
            if 'Shipment information sent to FedEx' in desc and not timeline['Shipment Created']['completed']:
                timeline['Shipment Created'] = {
                    'completed': True,
                    'timestamp': event['eventCreateTime']
                }
            
            # Check Shipment Picked Up
            elif 'Picked up' in desc and not timeline['Shipment Picked Up']['completed']:
                timeline['Shipment Picked Up'] = {
                    'completed': True,
                    'timestamp': event['eventCreateTime']
                }
            
            # Check In Transit
            elif ('Departed' in desc or 'Arrived' in desc):
                timeline['In Transit'] = {
                    'completed': True,
                    'timestamp': event['eventCreateTime']
                }
                # Always mark Shipment Picked Up as completed when In Transit is detected
                if not timeline['Shipment Picked Up']['completed']:
                    timeline['Shipment Picked Up'] = {
                        'completed': True,
                        'timestamp': in_transit_time or event['eventCreateTime']
                    }
            
            # Check Out For Delivery
            elif 'Out for Delivery' in desc and not timeline['Out For Delivery']['completed']:
                timeline['Out For Delivery'] = {
                    'completed': True,
                    'timestamp': event['eventCreateTime']
                }
            
            # Check Delivered
            elif 'Delivered' in desc and not timeline['Delivered']['completed']:
                timeline['Delivered'] = {
                    'completed': True,
                    'timestamp': event['eventCreateTime']
                }

        # Final check - if In Transit is completed, ensure Shipment Picked Up is also completed
        if timeline['In Transit']['completed'] and not timeline['Shipment Picked Up']['completed']:
            timeline['Shipment Picked Up'] = {
                'completed': True,
                'timestamp': in_transit_time or timeline['In Transit']['timestamp']
            }

        return timeline
    except Exception as e:
        logging.error(f"Error processing timeline for tracking {tracking_number}: {e}")
        return None

@app.route('/tracking/<tracking_number>')
@login_required
def get_tracking_details(tracking_number):
    try:
        # Get all events for this tracking number
        response = table.scan(
            FilterExpression='trackingNumber = :tn',
            ExpressionAttributeValues={':tn': tracking_number}
        )
        events = response['Items']
        
        # Continue scanning if we have more items
        while 'LastEvaluatedKey' in response:
            response = table.scan(
                FilterExpression='trackingNumber = :tn',
                ExpressionAttributeValues={':tn': tracking_number},
                ExclusiveStartKey=response['LastEvaluatedKey']
            )
            events.extend(response['Items'])

        # Sort events by timestamp
        events.sort(key=lambda x: x['eventCreateTime'])
        
        # Get the latest event for shipment details
        latest_event = events[-1] if events else {}
        first_event = events[0] if events else {}
        
        # Helper function to handle numeric values
        def get_package_value(event, key):
            value = event.get(key)
            if value is None or value == '' or value == 0 or value == '0':
                return 'N/A'
            # Add Kg to weight value
            if key == 'package_weight':
                return f"{value} Kg"
            return value

        # Helper function to format date
        def format_date(date_str):
            try:
                date = datetime.strptime(date_str, '%Y-%m-%dT%H:%M:%S%z')
                return date.strftime('%b %d, %Y')
            except:
                return 'N/A'

        # Helper function to truncate address
        def truncate_address(address, max_length=40):
            if not address or address == 'N/A':
                return 'N/A'
            if len(address) <= max_length:
                return address
            return address[:max_length] + '...'
        
        # Prepare shipment details
        shipment_details = {
            'timeline': get_tracking_timeline(tracking_number),
            'shipping_info': {
                'from': {
                    'location': truncate_address(first_event.get('SI_address', 'N/A')),
                    'date': format_date(first_event.get('eventCreateTime', ''))
                },
                'to': {
                    'location': truncate_address(latest_event.get('RI_address', 'N/A')),
                    'date': f"Estimated {format_date(latest_event.get('estimatedDeliveryDateEnd', ''))}"
                }
            },
            'sender': {
                'name': latest_event.get('SI_person_name', 'N/A'),
                'company': latest_event.get('SI_company', 'N/A'),
                'address': truncate_address(latest_event.get('SI_address', 'N/A')),
                'phone': latest_event.get('SI_person_phone', 'N/A')
            },
            'recipient': {
                'name': latest_event.get('RI_person_name', 'N/A'),
                'company': latest_event.get('RI_company', 'N/A'),
                'address': truncate_address(latest_event.get('RI_address', 'N/A')),
                'phone': latest_event.get('RI_person_phone', 'N/A')
            },
            'package': {
                'description': latest_event.get('package_desc', 'N/A'),
                'height': get_package_value(latest_event, 'package_height'),
                'weight': get_package_value(latest_event, 'package_weight'),
                'length': get_package_value(latest_event, 'package_length'),
                'width': get_package_value(latest_event, 'package_width'),
                'value': get_package_value(latest_event, 'package_value')
            }
        }
        
        return jsonify(shipment_details)
    except Exception as e:
        logging.error(f"Error fetching tracking details: {e}")
        return jsonify({'error': 'Failed to fetch tracking details'}), 500

@app.route('/analytics')
@login_required
def analytics():
    try:
        shipment_data = process_shipment_data()
        return render_template('analytics.html', 
                             dates=shipment_data['dates'],
                             counts=shipment_data['counts'],
                             status_data=shipment_data['status_data'],
                             courier_data=shipment_data['courier_data'],
                             lab_data=shipment_data['lab_data'])
    except Exception as e:
        logging.error(f"Error in analytics route: {e}")
        return render_template('analytics.html', 
                             dates=[], 
                             counts=[],
                             status_data={'labels': [], 'values': []},
                             courier_data={'labels': [], 'values': []},
                             lab_data={'labels': [], 'values': []})

@app.route('/')
@login_required
def index():
    try:
        page = request.args.get('page', 1, type=int)
        per_page = 25

        # Get all shipments in a single scan
        response = table.scan()
        all_events = response['Items']
        
        # Continue scanning if we have more items
        while 'LastEvaluatedKey' in response:
            response = table.scan(ExclusiveStartKey=response['LastEvaluatedKey'])
            all_events.extend(response['Items'])

        # Organize events by tracking number
        events_by_tracking = {}
        unique_shipments = {}
        delayed_tracking_numbers = set()

        for event in all_events:
            tracking_number = event['trackingNumber']
            
            # Track delayed shipments
            if 'Delay' in event.get('eventDescription', ''):
                delayed_tracking_numbers.add(tracking_number)
            
            # Group events by tracking number
            if tracking_number not in events_by_tracking:
                events_by_tracking[tracking_number] = []
            events_by_tracking[tracking_number].append(event)
            
            # Keep track of latest event for each tracking number
            if tracking_number not in unique_shipments:
                unique_shipments[tracking_number] = {
                    'latest_event': event,
                    'first_event_time': event['eventCreateTime']
                }
            else:
                current_time = datetime.strptime(event['eventCreateTime'], '%Y-%m-%dT%H:%M:%S%z')
                existing_time = datetime.strptime(unique_shipments[tracking_number]['latest_event']['eventCreateTime'], '%Y-%m-%dT%H:%M:%S%z')
                first_event_time = datetime.strptime(unique_shipments[tracking_number]['first_event_time'], '%Y-%m-%dT%H:%M:%S%z')
                
                # Update latest event if current is newer
                if current_time > existing_time:
                    unique_shipments[tracking_number]['latest_event'] = event
                
                # Update first event time if current is older
                if current_time < first_event_time:
                    unique_shipments[tracking_number]['first_event_time'] = event['eventCreateTime']

        # Process status for each tracking number
        for tracking_number, events in events_by_tracking.items():
            # Sort events by timestamp
            events.sort(key=lambda x: x['eventCreateTime'])
            
            # Get the first event's creation time
            first_event = events[0]
            unique_shipments[tracking_number]['first_event_time'] = first_event['eventCreateTime']
            
            # Determine status
            status = 'Shipment Created'
            for event in events:
                desc = event.get('eventDescription', '').strip()
                if 'Shipment Cancelled' in desc:
                    status = 'Shipment Cancelled'
                    break
                elif desc == 'Delivered':
                    status = 'Delivered'
                elif 'Out for Delivery' in desc:
                    status = 'Out For Delivery'
                elif ('Departed' in desc or 'Arrived' in desc):
                    status = 'In Transit'
                elif 'Picked up' in desc:
                    status = 'Shipment Picked Up'
                elif 'Shipment information sent to FedEx' in desc:
                    status = 'Shipment Created'

            # Add status to the latest shipment data
            unique_shipments[tracking_number]['latest_event']['currentStatus'] = status

        # Convert dictionary to list and sort by creation time
        all_shipments = []
        for tracking_data in unique_shipments.values():
            shipment = tracking_data['latest_event'].copy()
            shipment['eventCreateTime'] = tracking_data['first_event_time']  # Use the first event time
            all_shipments.append(shipment)
        
        all_shipments.sort(key=lambda x: x['eventCreateTime'], reverse=True)

        # Calculate counts
        delivered_count = sum(1 for shipment in all_shipments 
                            if shipment.get('currentStatus') == 'Delivered')
        cancelled_count = sum(1 for shipment in all_shipments 
                            if shipment.get('currentStatus') == 'Shipment Cancelled')
        in_transit_count = sum(1 for shipment in all_shipments 
                            if shipment.get('currentStatus') in ['In Transit', 'Out For Delivery'])
        delayed_count = len(delayed_tracking_numbers)

        # Calculate pagination
        total_shipments = len(all_shipments)
        total_pages = (total_shipments + per_page - 1) // per_page
        start_idx = (page - 1) * per_page
        end_idx = start_idx + per_page
        current_shipments = all_shipments[start_idx:end_idx]

        return render_template('index.html', 
                            shipments=current_shipments,
                            current_page=page,
                            total_pages=total_pages,
                            total_shipments=total_shipments,
                            in_transit_count=in_transit_count,
                            delivered_count=delivered_count,
                            delayed_count=delayed_count,
                            cancelled_count=cancelled_count)
    except Exception as e:
        logging.error(f"Error fetching data: {e}")
        return render_template('index.html', 
                             shipments=[], 
                             current_page=1, 
                             total_pages=1,
                             total_shipments=0,
                             in_transit_count=0,
                             delivered_count=0,
                             delayed_count=0,
                             cancelled_count=0)

@app.route('/shipments')
@login_required
def get_shipments():
    try:
        response = table.scan()
        data = response['Items']
        return jsonify(data)
    except Exception as e:
        logging.error(f"Error fetching data: {e}")
        return jsonify({'error': 'Failed to fetch data'})

if __name__ == '__main__':
    # In production, use gunicorn instead of app.run()
    app.run(host='0.0.0.0', port=5000) 