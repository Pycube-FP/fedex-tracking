# FedEx Tracking Application

A Flask web application for tracking FedEx shipments and analyzing shipment data.

## Features
- **Shipment Tracking:** Track FedEx shipments and view detailed status updates. Tracking data is fetched from a DynamoDB table.
- **Analytics Dashboard:** View various statistics and visualizations related to shipments, including sample analytics, batch analytics, location analytics, and alert analytics. The dashboard fetches data from JSON files and renders charts using Chart.js.
- **User Authentication:** Log in with hardcoded credentials (admin/admin123 or user/user123) to access the application's features. Login is required for most pages.
- **Batching and Receiving:** Create new batches, scan sample barcodes, and manage batch details on the batching page. View expected deliveries and mark them as received on the receiving page.
- **Alerts:** View, create, and manage alerts related to shipments. Alerts are stored in a JSON file.
- **Facility Management:** View, add, edit, and delete clinics and labs. Facility data is stored in a JSON file.
- **Responsive Design:** The application has a responsive design that adapts to different screen sizes, making it usable on both desktop and mobile devices.
- **Progressive Web App (PWA):** The app includes a manifest file and service worker, allowing it to be installed on devices and work offline.

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

## Application Structure

The application is built with Python and Flask for the backend, and HTML, CSS, and JavaScript for the frontend. Here's an overview of the main files and directories:

- `app.py`: The main Flask application file containing route handlers and application logic.
- `templates/`: Directory containing HTML templates for the application's pages.
- `static/`: Directory containing static assets like CSS, JavaScript, and images.
- `requirements.txt`: File listing the Python dependencies required by the application.
- `alerts.json`: JSON file storing alert data.
- `facilities.json`: JSON file storing facility (clinics and labs) data.
- `recent_batches.json`: JSON file storing recent batch data.
- `expected_deliveries.json`: JSON file storing expected delivery data.
- `received_deliveries.json`: JSON file storing received delivery data.

## Contributing

If you'd like to contribute to this project, please follow these steps:

1. Fork the repository
2. Create a new branch for your feature or bug fix
3. Make your changes and commit them with descriptive messages
4. Push your changes to your forked repository
5. Open a pull request to the main repository

Please ensure your code follows the existing style and includes appropriate tests and documentation.

## License

This project is open-source and available under the [MIT License](LICENSE).

## Contact

If you have any questions, issues, or suggestions, please feel free to open an issue on the GitHub repository or contact the project maintainer at [maintainer@example.com](mailto:maintainer@example.com). 