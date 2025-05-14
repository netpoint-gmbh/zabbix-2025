# Zabbix Conference 2025 - Germany

In this talk, I will present how we built a scalable and reliable monitoring system leveraging Zabbix for monitoring, Grafana for customer-facing visualizations, and ServiceNow as our IT Service Management (ITSM) platform. 

I will explain how this integrated solution has significantly enhanced customer success across multiple global clients and locations. 

I will share our architecture, including the deployment of Zabbix proxies in customer sites worldwide, centralized data processing in Azure, and the separation of Grafana dashboards by customer organization. 

A key focus will be on the deep integration with ServiceNow: 
- Automatic incident creation from Zabbix alerts 
- Bi-directional synchronization of configuration items (CIs) 
- Linked acknowledgments and status updates between Zabbix and ServiceNow 
- Automated knowledge base article generation and linking for each alert trigger 

I will also discuss the challenges we encountered, particularly in the areas of ticket routing and ServiceNow integration, and highlight lessons learned along the way. 