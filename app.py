from flask import Flask, jsonify, render_template, request, redirect, url_for, session, flash, send_from_directory
import boto3
import logging
from collections import defaultdict
from datetime import datetime, timezone
from functools import wraps
import os
from dotenv import load_dotenv
import json

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

# Configure logging
logging.basicConfig(level=logging.INFO)
app.logger.setLevel(logging.INFO)

# Hardcoded users for demo (in production, use a database and hash passwords)
USERS = {
    'admin': 'admin123',
    'user': 'user123'
}

# File to store alerts
ALERTS_FILE = 'alerts.json'

# Facility management constants
FACILITIES_FILE = 'facilities.json'

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
                # Parse the date with timezone info
                date = datetime.strptime(date_str, '%Y-%m-%dT%H:%M:%S%z')
                # Convert to local time (like JavaScript does)
                local_date = date.astimezone(tz=None)  # None means local timezone
                formatted = local_date.strftime('%b %d, %Y')
                return formatted
            except Exception as e:
                app.logger.error(f"Error formatting date: {e}")
                return date_str

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

def parse_date(date_str):
    try:
        # Try parsing as ISO 8601
        dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
    except ValueError:
        # Fallback to parsing as '%m/%d/%Y, %I:%M:%S %p'
        dt = datetime.strptime(date_str, '%m/%d/%Y, %I:%M:%S %p')
    # Return offset-naive datetime
    return dt.replace(tzinfo=None)

@app.route('/api/analytics')
def get_analytics():
    try:
        start_date = request.args.get('start')
        end_date = request.args.get('end')
        
        # Load data from files
        with open('recent_batches.json', 'r') as f:
            batches_data = json.load(f)['batches']
        
        with open('alerts.json', 'r') as f:
            alerts_data = json.load(f)
            
        with open('expected_deliveries.json', 'r') as f:
            deliveries_data = json.load(f)

        # Filter data by date range if provided
        if start_date and end_date:
            start = parse_date(start_date)
            end = parse_date(end_date)
            
            batches_data = [b for b in batches_data 
                          if start <= parse_date(b['createdDate']) <= end]
            
            alerts_data = [a for a in alerts_data 
                         if start <= parse_date(a['date']) <= end]
            
            deliveries_data = [d for d in deliveries_data 
                             if start <= parse_date(d['createdAt']) <= end]

        # Process Sample Analytics
        sample_types = defaultdict(int)
        daily_samples = defaultdict(int)
        total_samples = 0
        pending_samples = 0

        for batch in batches_data:
            batch_date = batch['createdDate'].split(',')[0]
            for sample in batch.get('samples', []):
                sample_types[sample['type']] += 1
                daily_samples[batch_date] += 1
                total_samples += 1
                if batch['status'] == 'Pending':
                    pending_samples += 1

        # Process Batch Analytics
        batch_statuses = defaultdict(int)
        processing_times = defaultdict(list)
        active_batches = 0

        for batch in batches_data:
            batch_statuses[batch['status']] += 1
            if batch['status'] in ['Pending', 'In Transit']:
                active_batches += 1
            
            # Calculate processing time for completed batches
            if batch['status'] == 'Delivered' and 'createdDate' in batch:
                created = parse_date(batch['createdDate'])
                # Find matching delivery in expected_deliveries for actual delivery date
                delivery = next((d for d in deliveries_data if d['batchId'] == batch['id']), None)
                if delivery and 'shippedAt' in delivery:
                    delivered = parse_date(delivery['shippedAt'])
                    processing_time = (delivered - created).total_seconds() / 3600  # hours
                    processing_times[batch['status']].append(processing_time)

        # Process Location Analytics
        clinic_volumes = defaultdict(int)
        lab_volumes = defaultdict(int)
        active_routes = set()

        for batch in batches_data:
            clinic_volumes[batch['origin']] += 1
            lab_volumes[batch['destination']] += 1
            if batch['status'] in ['Pending', 'In Transit']:
                active_routes.add(f"{batch['origin']}-{batch['destination']}")

        # Process Alert Analytics
        alert_types = defaultdict(int)
        alert_trends = defaultdict(int)
        open_alerts = 0
        resolution_times = []

        for alert in alerts_data:
            alert_types[alert['type']] += 1
            alert_date = alert['date'].split('T')[0]
            alert_trends[alert_date] += 1
            
            if alert['status'] == 'Action Required':
                open_alerts += 1
            
            # Calculate resolution time for completed alerts
            if alert['status'] == 'Completed' and 'completedDate' in alert:
                created = parse_date(alert['date'])
                completed = parse_date(alert['completedDate'])
                resolution_time = (completed - created).total_seconds() / 3600  # hours
                resolution_times.append(resolution_time)

        # Prepare response data
        response_data = {
            'samples': {
                'total': total_samples,
                'average': round(total_samples / len(batches_data) if batches_data else 0, 1),
                'successRate': round((total_samples - pending_samples) / total_samples * 100 if total_samples else 0, 1),
                'pending': pending_samples,
                'types': {
                    'labels': list(sample_types.keys()),
                    'values': list(sample_types.values())
                },
                'daily': {
                    'labels': sorted(daily_samples.keys()),
                    'values': [daily_samples[date] for date in sorted(daily_samples.keys())]
                }
            },
            'batches': {
                'total': len(batches_data),
                'active': active_batches,
                'successRate': round(batch_statuses['Delivered'] / len(batches_data) * 100 if batches_data else 0, 1),
                'avgProcessingTime': round(sum(sum(times) for times in processing_times.values()) / 
                                        sum(len(times) for times in processing_times.values()) 
                                        if any(processing_times.values()) else 0, 1),
                'status': {
                    'labels': list(batch_statuses.keys()),
                    'values': list(batch_statuses.values())
                },
                'processingTimes': {
                    'labels': list(processing_times.keys()),
                    'values': [round(sum(times)/len(times), 1) if times else 0 
                              for times in processing_times.values()]
                }
            },
            'locations': {
                'active': len(set(b['origin'] for b in batches_data) | set(b['destination'] for b in batches_data)),
                'activeRoutes': len(active_routes),
                'routeEfficiency': round(len(set(f"{b['origin']}-{b['destination']}" for b in batches_data)) / 
                                      (len(set(b['origin'] for b in batches_data)) * 
                                       len(set(b['destination'] for b in batches_data))) * 100, 1),
                'avgDeliveryTime': round(sum(sum(times) for times in processing_times.values()) / 
                                       sum(len(times) for times in processing_times.values()) 
                                       if any(processing_times.values()) else 0, 1),
                'topClinics': {
                    'labels': sorted(clinic_volumes.keys(), key=clinic_volumes.get, reverse=True)[:10],
                    'values': [clinic_volumes[clinic] for clinic in 
                              sorted(clinic_volumes.keys(), key=clinic_volumes.get, reverse=True)[:10]]
                },
                'topLabs': {
                    'labels': sorted(lab_volumes.keys(), key=lab_volumes.get, reverse=True)[:10],
                    'values': [lab_volumes[lab] for lab in 
                              sorted(lab_volumes.keys(), key=lab_volumes.get, reverse=True)[:10]]
                }
            },
            'alerts': {
                'total': len(alerts_data),
                'open': open_alerts,
                'resolutionRate': round((len(alerts_data) - open_alerts) / len(alerts_data) * 100 
                                      if alerts_data else 0, 1),
                'avgResolutionTime': round(sum(resolution_times) / len(resolution_times) 
                                         if resolution_times else 0, 1),
                'types': {
                    'labels': list(alert_types.keys()),
                    'values': list(alert_types.values())
                },
                'trends': {
                    'labels': sorted(alert_trends.keys()),
                    'values': [alert_trends[date] for date in sorted(alert_trends.keys())]
                }
            }
        }
        
        return jsonify(response_data)
        
    except Exception as e:
        app.logger.error(f"Error generating analytics data: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/analytics')
@login_required
def analytics():
    try:
        return render_template('analytics.html')
    except Exception as e:
        app.logger.error(f"Error in analytics route: {e}")
        return render_template('analytics.html')

@app.route('/')
@login_required
def index():
    try:
        page = request.args.get('page', 1, type=int)
        search_query = request.args.get('search', '').strip()
        
        # Get all shipments from DynamoDB
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
            shipment['eventCreateTime'] = tracking_data['first_event_time']
            all_shipments.append(shipment)
        
        # Sort shipments by creation time
        all_shipments.sort(key=lambda x: x['eventCreateTime'], reverse=True)
        
        # Calculate KPI stats before applying search filter
        total_shipments = len(all_shipments)
        in_transit_count = sum(1 for s in all_shipments if s['currentStatus'] in ['In Transit', 'Out For Delivery'])
        delivered_count = sum(1 for s in all_shipments if s['currentStatus'] == 'Delivered')
        delayed_count = len(delayed_tracking_numbers)
        cancelled_count = sum(1 for s in all_shipments if s['currentStatus'] == 'Shipment Cancelled')
        
        # Apply search filter if provided (only affects displayed shipments, not KPI stats)
        filtered_shipments = all_shipments
        if search_query:
            filtered_shipments = [s for s in all_shipments if search_query.lower() in s['trackingNumber'].lower()]
        
        # Pagination on filtered results
        per_page = 25
        total_pages = (len(filtered_shipments) + per_page - 1) // per_page
        page = min(max(page, 1), total_pages) if total_pages > 0 else 1
        
        start_idx = (page - 1) * per_page
        end_idx = start_idx + per_page
        current_shipments = filtered_shipments[start_idx:end_idx]
        
        # Calculate visible pages for pagination
        if total_pages <= 3:
            visible_pages = range(1, total_pages + 1)
        else:
            if page <= 2:
                visible_pages = range(1, 4)
            elif page >= total_pages - 1:
                visible_pages = range(total_pages - 2, total_pages + 1)
            else:
                visible_pages = range(page - 1, page + 2)

        return render_template('index.html',
                            shipments=current_shipments,
                            total_shipments=total_shipments,
                            in_transit_count=in_transit_count,
                            delivered_count=delivered_count,
                            delayed_count=delayed_count,
                            cancelled_count=cancelled_count,
                            current_page=page,
                            total_pages=total_pages,
                            visible_pages=visible_pages,
                            search_query=search_query)
                            
    except Exception as e:
        app.logger.error(f"Error in index route: {str(e)}")
        return render_template('index.html',
                            shipments=[],
                            total_shipments=0,
                            in_transit_count=0,
                            delivered_count=0,
                            delayed_count=0,
                            cancelled_count=0,
                            current_page=1,
                            total_pages=1,
                            visible_pages=range(1, 2),
                            search_query=search_query,
                            error="An error occurred while loading the data. Please try again later.")

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

@app.route('/batching')
@login_required
def batching():
    return render_template('batching.html')

@app.route('/receiving')
@login_required
def receiving():
    return render_template('receiving.html')

@app.route('/alerts')
@login_required
def alerts():
    return render_template('alerts.html')

def load_alerts():
    try:
        if not os.path.exists(ALERTS_FILE):
            # Create file with empty array if it doesn't exist
            save_alerts([])
            return []
        
        with open(ALERTS_FILE, 'r') as f:
            content = f.read().strip()
            if not content:  # If file is empty
                return []
            return json.loads(content)
    except json.JSONDecodeError:
        # If file is corrupted, reset it
        save_alerts([])
        return []
    except Exception as e:
        app.logger.error(f"Error loading alerts: {e}")
        return []

def save_alerts(alerts):
    try:
        with open(ALERTS_FILE, 'w') as f:
            json.dump(alerts, f, indent=2)
    except Exception as e:
        app.logger.error(f"Error saving alerts: {e}")
        raise

@app.route('/api/alerts', methods=['GET'])
def get_alerts():
    alerts = load_alerts()
    return jsonify(alerts)

@app.route('/api/alerts', methods=['POST'])
def create_alert():
    alert_data = request.json
    # Ensure status is set to "Action Required" for new alerts
    alert_data['status'] = 'Action Required'
    alerts = load_alerts()
    
    # Check for existing alert with same batch ID and type that is not completed
    existing_alert = next(
        (alert for alert in alerts 
         if alert['batchId'] == alert_data['batchId'] 
         and alert['type'] == alert_data['type']
         and alert['status'] != 'Completed'),
        None
    )
    
    if existing_alert:
        # If alert exists and is not completed, don't create a duplicate
        return jsonify({
            "message": "Alert already exists for this batch",
            "alert": existing_alert
        }), 200
    
    # If no existing alert found, create new one
    alerts.append(alert_data)
    save_alerts(alerts)
    return jsonify({"message": "Alert created successfully", "alert": alert_data}), 201

@app.route('/api/alerts/clear', methods=['POST'])
def clear_alerts():
    save_alerts([])
    return jsonify({"message": "Alerts cleared successfully"})

@app.route('/api/alerts/<alert_id>', methods=['PUT'])
def update_alert(alert_id):
    try:
        data = request.json
        alerts = load_alerts()
        
        # Find and update the alert
        for alert in alerts:
            if alert['alertId'] == alert_id:
                alert.update(data)
                break
        
        save_alerts(alerts)
        return jsonify({"message": "Alert updated successfully"}), 200
    except Exception as e:
        app.logger.error(f"Error updating alert: {e}")
        return jsonify({"error": "Failed to update alert"}), 500

@app.route('/api/batches', methods=['GET'])
def get_batches():
    try:
        with open('recent_batches.json', 'r') as f:
            data = json.load(f)
            return jsonify(data['batches'])
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/batches', methods=['POST'])
def create_batch():
    try:
        new_batch = request.json
        with open('recent_batches.json', 'r') as f:
            data = json.load(f)
        
        data['batches'].append(new_batch)
        
        with open('recent_batches.json', 'w') as f:
            json.dump(data, f, indent=4)
        
        return jsonify({'message': 'Batch created successfully'}), 201
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/batches/<batch_id>', methods=['PUT'])
def update_batch(batch_id):
    try:
        updated_batch = request.json
        with open('recent_batches.json', 'r') as f:
            data = json.load(f)
        
        for i, batch in enumerate(data['batches']):
            if batch['id'] == batch_id:
                data['batches'][i] = updated_batch
                break
        
        with open('recent_batches.json', 'w') as f:
            json.dump(data, f, indent=4)
        
        return jsonify({'message': 'Batch updated successfully'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/batches/<batch_id>/ship', methods=['POST'])
def ship_batch(batch_id):
    try:
        # Get the batch data from request
        batch_data = request.json
        
        # Update batch status to shipped
        batch_data['status'] = 'Shipped'
        batch_data['shippedAt'] = datetime.now().isoformat()
        
        # Add to expected deliveries
        expected_deliveries = []
        if os.path.exists('expected_deliveries.json'):
            with open('expected_deliveries.json', 'r') as f:
                expected_deliveries = json.load(f)
        
        expected_deliveries.append(batch_data)
        
        # Save updated expected deliveries
        with open('expected_deliveries.json', 'w') as f:
            json.dump(expected_deliveries, f, indent=4)
        
        return jsonify({'message': 'Batch shipped successfully'}), 200
        
    except Exception as e:
        app.logger.error(f"Error shipping batch: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/expected-deliveries', methods=['POST'])
def add_expected_delivery():
    try:
        data = request.get_json()
        
        # Load existing expected deliveries
        try:
            with open('expected_deliveries.json', 'r') as f:
                expected_deliveries = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            expected_deliveries = []
        
        # Check if batch already exists
        if not any(delivery['batchId'] == data['batchId'] for delivery in expected_deliveries):
            # Add new delivery
            expected_deliveries.append(data)
            
            # Save back to file
            with open('expected_deliveries.json', 'w') as f:
                json.dump(expected_deliveries, f, indent=4)
            
            return jsonify({'message': 'Delivery added successfully'}), 201
        else:
            return jsonify({'message': 'Batch already exists in expected deliveries'}), 200
            
    except Exception as e:
        print(f"Error adding expected delivery: {str(e)}")
        return jsonify({'error': str(e)}), 500
    
@app.route('/api/receiving/expected', methods=['GET'])
@login_required
def get_expected_deliveries():
    try:
        if not os.path.exists('expected_deliveries.json'):
            return jsonify([])
            
        with open('expected_deliveries.json', 'r') as f:
            deliveries = json.load(f)
        return jsonify(deliveries), 200
        
    except Exception as e:
        app.logger.error(f"Error getting expected deliveries: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/receiving/receive', methods=['POST'])
@login_required
def receive_batch():
    try:
        # Get the delivery data from request
        delivery_data = request.json
        
        # Load existing received deliveries
        received_deliveries = []
        if os.path.exists('received_deliveries.json'):
            with open('received_deliveries.json', 'r') as f:
                received_deliveries = json.load(f)
        
        # Add new delivery to received deliveries
        received_deliveries.append(delivery_data)
        
        # Save updated received deliveries
        with open('received_deliveries.json', 'w') as f:
            json.dump(received_deliveries, f)
        
        # Remove from expected deliveries
        if os.path.exists('expected_deliveries.json'):
            with open('expected_deliveries.json', 'r') as f:
                expected_deliveries = json.load(f)
            
            # Filter out the received batch
            expected_deliveries = [d for d in expected_deliveries if d['batchId'] != delivery_data['batchId']]
            
            with open('expected_deliveries.json', 'w') as f:
                json.dump(expected_deliveries, f)
        
        return jsonify({'message': 'Batch received successfully'}), 200
        
    except Exception as e:
        app.logger.error(f"Error receiving batch: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/receiving/received', methods=['GET'])
@login_required
def get_received_deliveries():
    try:
        if not os.path.exists('received_deliveries.json'):
            return jsonify([])
            
        with open('received_deliveries.json', 'r') as f:
            deliveries = json.load(f)
        return jsonify(deliveries), 200
        
    except Exception as e:
        app.logger.error(f"Error getting received deliveries: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/receiving/notify', methods=['POST'])
def update_notification_status():
    try:
        data = request.json
        batch_id = data.get('batchId')
        
        # Read the current received deliveries
        with open('received_deliveries.json', 'r') as f:
            received_deliveries = json.load(f)
        
        # Update the notification status for the specified batch
        for delivery in received_deliveries:
            if delivery['batchId'] == batch_id:
                delivery['notified'] = True
                break
        
        # Write back to the file
        with open('received_deliveries.json', 'w') as f:
            json.dump(received_deliveries, f, indent=4)
        
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

def load_facilities():
    try:
        with open(FACILITIES_FILE, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return {"clinics": [], "labs": []}

def save_facilities(facilities):
    with open(FACILITIES_FILE, 'w') as f:
        json.dump(facilities, f, indent=4)

@app.route('/facilities')
@login_required
def facilities():
    facilities_data = load_facilities()
    return render_template('facilities.html', 
                         clinics=facilities_data['clinics'], 
                         labs=facilities_data['labs'])

@app.route('/api/facilities', methods=['GET'])
@login_required
def get_facilities():
    return jsonify(load_facilities())

@app.route('/api/facilities', methods=['POST'])
@login_required
def add_facility():
    try:
        facility = request.json
        print(f"Received new facility data: {json.dumps(facility, indent=2)}")
        
        # Load facilities using the correct path
        facilities = load_facilities()
        print(f"Current facilities before adding: {json.dumps(facilities, indent=2)}")
        
        # Add the new facility to the appropriate list
        if facility['type'] == 'clinic':
            facilities['clinics'].append(facility)
            print(f"Added new clinic: {json.dumps(facility, indent=2)}")
        else:
            facilities['labs'].append(facility)
            print(f"Added new lab: {json.dumps(facility, indent=2)}")
            
        # Save using the correct function
        save_facilities(facilities)
        print(f"Facilities saved successfully to {FACILITIES_FILE}")
            
        return jsonify(facility), 201
    except Exception as e:
        error_msg = f"Error saving facility: {str(e)}"
        print(error_msg)
        import traceback
        print(f"Traceback: {traceback.format_exc()}")
        return jsonify({'message': error_msg}), 400

@app.route('/api/facilities/<facility_id>', methods=['GET'])
@login_required
def get_facility(facility_id):
    facilities = load_facilities()
    facility_type = 'clinics' if facility_id.startswith('C') else 'labs'
    
    for facility in facilities[facility_type]:
        if facility['id'] == facility_id:
            return jsonify(facility)
    
    return jsonify({'error': 'Facility not found'}), 404

@app.route('/api/facilities/<facility_id>', methods=['PUT'])
@login_required
def update_facility(facility_id):
    try:
        updated_facility = request.json
        print(f"Updating facility {facility_id} with data: {json.dumps(updated_facility, indent=2)}")
        
        # Load facilities using the correct path
        facilities = load_facilities()
        print(f"Current facilities before update: {json.dumps(facilities, indent=2)}")
        
        # Update in the appropriate list
        facility_list = facilities['clinics'] if updated_facility['type'] == 'clinic' else facilities['labs']
        found = False
        for i, facility in enumerate(facility_list):
            if facility['facilityId'] == facility_id:
                facility_list[i] = updated_facility
                found = True
                print(f"Updated facility at index {i}")
                break
                
        if not found:
            error_msg = f"Facility with ID {facility_id} not found"
            print(error_msg)
            return jsonify({'message': error_msg}), 404
        
        # Save using the correct function
        save_facilities(facilities)
        print(f"Facilities saved successfully to {FACILITIES_FILE}")
            
        return jsonify(updated_facility)
    except Exception as e:
        error_msg = f"Error updating facility: {str(e)}"
        print(error_msg)
        import traceback
        print(f"Traceback: {traceback.format_exc()}")
        return jsonify({'message': error_msg}), 400

@app.route('/api/facilities/<facility_id>', methods=['DELETE'])
@login_required
def delete_facility(facility_id):
    try:
        print(f"Attempting to delete facility {facility_id}")
        
        # Load facilities using the correct path
        facilities = load_facilities()
        print(f"Current facilities before delete: {json.dumps(facilities, indent=2)}")
        
        found = False
        # Try to find and delete from clinics
        for i, facility in enumerate(facilities['clinics']):
            if facility['facilityId'] == facility_id:
                del facilities['clinics'][i]
                found = True
                print(f"Deleted clinic at index {i}")
                break
        
        if not found:
            # If not found in clinics, try labs
            for i, facility in enumerate(facilities['labs']):
                if facility['facilityId'] == facility_id:
                    del facilities['labs'][i]
                    found = True
                    print(f"Deleted lab at index {i}")
                    break
                    
        if not found:
            error_msg = f"Facility with ID {facility_id} not found"
            print(error_msg)
            return jsonify({'message': error_msg}), 404
        
        # Save using the correct function
        save_facilities(facilities)
        print(f"Facilities saved successfully to {FACILITIES_FILE}")
            
        return '', 204
    except Exception as e:
        error_msg = f"Error deleting facility: {str(e)}"
        print(error_msg)
        import traceback
        print(f"Traceback: {traceback.format_exc()}")
        return jsonify({'message': error_msg}), 400

@app.route('/api/facilities/list', methods=['GET'])
def get_facilities_list():
    try:
        with open('facilities.json', 'r') as f:
            facilities = json.load(f)
            return jsonify({
                'clinics': facilities['clinics'],
                'labs': facilities['labs']
            })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/static/manifest.json')
def serve_manifest():
    return send_from_directory('static', 'manifest.json')

@app.route('/static/service-worker.js')
def serve_service_worker():
    return send_from_directory('static', 'service-worker.js')

@app.route('/api/expected-deliveries/<batch_id>', methods=['GET', 'PUT'])
def manage_expected_delivery(batch_id):
    try:
        # Load existing expected deliveries
        with open('expected_deliveries.json', 'r') as f:
            expected_deliveries = json.load(f)
        
        if request.method == 'GET':
            # Find the delivery with matching batch_id
            delivery = next((d for d in expected_deliveries if d['batchId'] == batch_id), None)
            if delivery:
                return jsonify(delivery), 200
            else:
                return jsonify({'error': 'Delivery not found'}), 404
                
        elif request.method == 'PUT':
            data = request.get_json()
            
            # Find and update the delivery
            for delivery in expected_deliveries:
                if delivery['batchId'] == batch_id:
                    # Update only the status field
                    delivery['status'] = data['status']
                    
                    # Save the updated deliveries back to file
                    with open('expected_deliveries.json', 'w') as f:
                        json.dump(expected_deliveries, f, indent=4)
                    
                    return jsonify({'message': 'Delivery updated successfully'}), 200
            
            return jsonify({'error': 'Delivery not found'}), 404
            
    except Exception as e:
        app.logger.error(f"Error managing expected delivery: {e}")
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    # Enable debug mode for hot reloading and detailed error messages
    app.debug = True
    app.run(host='0.0.0.0', port=5000, debug=True) 