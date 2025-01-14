# FedEx Tracking Application

A Flask web application for tracking FedEx shipments and analyzing shipment data.

## Features
- Shipment tracking with detailed status updates
- Analytics dashboard with shipment statistics
- User authentication
- Responsive design

## Prerequisites
- Python 3.8+
- AWS Account with DynamoDB access
- Git

## Local Development Setup

1. Clone the repository:
```bash
git clone <repository-url>
cd fedex-tracking
```

2. Create and activate a virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Create a `.env` file in the project root with the following variables:
```
AWS_ACCESS_KEY_ID=your-access-key
AWS_SECRET_ACCESS_KEY=your-secret-key
AWS_REGION=your-region
FLASK_SECRET_KEY=your-secret-key
```

5. Run the development server:
```bash
python app.py
```

## EC2 Deployment

1. Launch an EC2 instance with Ubuntu Server 22.04 LTS
2. Install required packages:
```bash
sudo apt update
sudo apt install python3-pip python3-venv nginx
```

3. Clone the repository:
```bash
git clone <repository-url>
cd fedex-tracking
```

4. Set up the Python environment:
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

5. Create the `.env` file with your credentials

6. Set up Gunicorn:
```bash
sudo nano /etc/systemd/system/fedex-tracking.service
```

Add the following content:
```ini
[Unit]
Description=Gunicorn instance to serve FedEx Tracking application
After=network.target

[Service]
User=ubuntu
WorkingDirectory=/home/ubuntu/fedex-tracking
Environment="PATH=/home/ubuntu/fedex-tracking/venv/bin"
ExecStart=/home/ubuntu/fedex-tracking/venv/bin/gunicorn --workers 3 --bind 0.0.0.0:5000 app:app

[Install]
WantedBy=multi-user.target
```

7. Start and enable the service:
```bash
sudo systemctl start fedex-tracking
sudo systemctl enable fedex-tracking
```

8. Configure Nginx:
```bash
sudo nano /etc/nginx/sites-available/fedex-tracking
```

Add the following content:
```nginx
server {
    listen 80;
    server_name your_domain_or_ip;

    location / {
        proxy_pass http://localhost:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

9. Enable the site and restart Nginx:
```bash
sudo ln -s /etc/nginx/sites-available/fedex-tracking /etc/nginx/sites-enabled
sudo systemctl restart nginx
```

## Updating the Application

To update the application with new changes:

1. Push changes to GitHub
2. On the EC2 instance:
```bash
cd fedex-tracking
git pull
sudo systemctl restart fedex-tracking
```

## Security Considerations
- Keep your `.env` file secure and never commit it to version control
- Use appropriate security groups for your EC2 instance
- Regularly update dependencies
- Consider using AWS Secrets Manager for credential management
- Enable HTTPS using Let's Encrypt 