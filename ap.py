import json
import boto3
import os
from datetime import datetime, timedelta
import matplotlib.pyplot as plt
import io
import base64

dynamodb = boto3.resource('dynamodb')
table = dynamodb.Table(os.environ['ORDERS_TABLE'])
s3 = boto3.client('s3')
sns = boto3.client('sns')
reports_bucket = os.environ['REPORTS_BUCKET']
report_topic = os.environ['REPORT_TOPIC']

def lambda_handler(event, context):
    try:
        # Calculate date range for yesterday
        end_date = datetime.now()
        start_date = end_date - timedelta(days=1)
        
        # Format dates for query
        start_date_str = start_date.isoformat()
        end_date_str = end_date.isoformat()
        
        # Query DynamoDB for yesterday's orders
        response = table.query(
            IndexName='timestamp-index',
            KeyConditionExpression='#ts BETWEEN :start AND :end',
            ExpressionAttributeNames={
                '#ts': 'timestamp'
            },
            ExpressionAttributeValues={
                ':start': start_date_str,
                ':end': end_date_str
            }
        )
        
        orders = response.get('Items', [])
        
        # Generate analytics
        analytics = generate_analytics(orders)
        
        # Generate visualizations
        visualizations = generate_visualizations(orders)
        
        # Save report to S3
        report_key = f"reports/daily/{datetime.now().strftime('%Y-%m-%d')}.json"
        s3.put_object(
            Bucket=reports_bucket,
            Key=report_key,
            Body=json.dumps(analytics, indent=2)
        )
        
        # Save visualizations to S3
        for viz_name, viz_data in visualizations.items():
            viz_key = f"reports/daily/{datetime.now().strftime('%Y-%m-%d')}_{viz_name}.png"
            s3.put_object(
                Bucket=reports_bucket,
                Key=viz_key,
                Body=viz_data
            )
        
        # Send notification
        send_report_notification(analytics, report_key)
        
        return {
            'statusCode': 200,
            'body': json.dumps({
                'message': 'Daily analytics report generated successfully',
                'report_key': report_key,
                'order_count': len(orders)
            })
        }
        
    except Exception as e:
        return {
            'statusCode': 500,
            'body': json.dumps(f'Error generating analytics: {str(e)}')
        }

def generate_analytics(orders):
    total_orders = len(orders)
    
    if total_orders == 0:
        return {
            'date': datetime.now().strftime('%Y-%m-%d'),
            'total_orders': 0,
            'total_revenue': 0,
            'average_order_value': 0,
            'top_products': [],
            'hourly_trends': {}
        }
    
    # Calculate total revenue
    total_revenue = sum(float(order.get('amount', 0)) for order in orders)
    
    # Calculate average order value
    average_order_value = total_revenue / total_orders
    
    # Find top products
    product_sales = {}
    for order in orders:
        for item in order.get('items', []):
            product_id = item.get('product_id', 'unknown')
            quantity = item.get('quantity', 0)
            product_sales[product_id] = product_sales.get(product_id, 0) + quantity
    
    top_products = sorted(product_sales.items(), key=lambda x: x[1], reverse=True)[:5]
    
    # Calculate hourly trends
    hourly_trends = {}
    for hour in range(24):
        hourly_trends[hour] = 0
    
    for order in orders:
        try:
            order_time = datetime.fromisoformat(order['timestamp'])
            hour = order_time.hour
            hourly_trends[hour] += 1
        except:
            continue
    
    return {
        'date': datetime.now().strftime('%Y-%m-%d'),
        'total_orders': total_orders,
        'total_revenue': round(total_revenue, 2),
        'average_order_value': round(average_order_value, 2),
        'top_products': top_products,
        'hourly_trends': hourly_trends
    }

def generate_visualizations(orders):
    visualizations = {}
    
    # Generate hourly sales trend chart
    if orders:
        hourly_trends = {}
        for hour in range(24):
            hourly_trends[hour] = 0
        
        for order in orders:
            try:
                order_time = datetime.fromisoformat(order['timestamp'])
                hour = order_time.hour
                hourly_trends[hour] += float(order.get('amount', 0))
            except:
                continue
        
        hours = list(hourly_trends.keys())
        sales = list(hourly_trends.values())
        
        plt.figure(figsize=(10, 6))
        plt.bar(hours, sales, color='skyblue')
        plt.title('Hourly Sales Trend')
        plt.xlabel('Hour of Day')
        plt.ylabel('Total Sales ($)')
        plt.xticks(hours)
        plt.grid(axis='y', linestyle='--', alpha=0.7)
        
        img_data = io.BytesIO()
        plt.savefig(img_data, format='png')
        img_data.seek(0)
        visualizations['hourly_sales'] = img_data.getvalue()
        plt.close()
    
    return visualizations

def send_report_notification(analytics, report_key):
    report_url = f"https://{reports_bucket}.s3.amazonaws.com/{report_key}"
    
    message = f"""Daily Sales Report - {analytics['date']}
    
Total Orders: {analytics['total_orders']}
Total Revenue: ${analytics['total_revenue']}
Average Order Value: ${analytics['average_order_value']}

Top Products:
{json.dumps(analytics['top_products'], indent=2)}

View full report: {report_url}
"""
    
    sns.publish(
        TopicArn=report_topic,
        Subject=f"Daily Sales Report - {analytics['date']}",
        Message=message
    )
    
