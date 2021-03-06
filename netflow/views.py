import logging
from django.utils.translation import ugettext_lazy as _

from horizon import tables
from horizon import tabs
from openstack_dashboard.dashboards.project.netflow import tables as project_tables
from openstack_dashboard.dashboards.project.netflow import tabs as project_tabs
from openstack_dashboard import api
from horizon import exceptions
from horizon.utils import memoized
from django.views.generic.base import TemplateView
from django.core.urlresolvers import reverse
import datetime
import time
from django.views.decorators.csrf import csrf_exempt
from django.http import HttpResponse
import re
from openstack_dashboard import usage
from NetFlowTotal import NetFlowTotal, NetFlowManager, NetRate, Meters
LOG = logging.getLogger(__name__)

totaldict = {}

class IndexView(tables.MultiTableView, usage.BaseUsage):
    table_classes = (project_tables.NetFlowTable, project_tables.TotalNetFlowTable)
    template_name = 'project/netflow/index.html'

    def has_more_data(self, table):
        return self._more

    def get_context_data(self,**kwargs):
        context = super(IndexView, self).get_context_data(**kwargs)
        context['form'] = self.get_form()
        import MySQLdb
        region = self.request.user.services_region
        project_id = self.request.user.project_id
        start = self.request.GET.get('start')
        end = self.request.GET.get('end')
        if not end or not start:
            start = datetime.datetime.now().strftime('%Y-%m-01')
            end = datetime.datetime.now().strftime('%Y-%m-%d')
        try:
            conn=MySQLdb.connect(host='172.30.251.30',user='cloud',passwd='NanHui-F2-Cloud!@#',port=6020)
            cur=conn.cursor()
            conn.select_db('netflow')
            if start == end:
                cur.execute('select in_rate,out_rate,date from netrate_project where region="%s" and project_id="%s" and begin_rate_date>="%s 00:00:00" and end_rate_date<="%s 23:59:59" group by begin_rate_date order by begin_rate_date' % (region, project_id, start, end))
                period = 600 * 1000
            else:
                cur.execute('select in_rate,out_rate,date from netrate_project where region="%s" and project_id="%s" and begin_rate_date>"%s 00:00:00" and end_rate_date<"%s 23:59:59" group by begin_rate_date order by begin_rate_date' % (region, project_id, start, end))
                period = 600 * 1000
            results = cur.fetchall()
            conn.commit()
            cur.close()
            conn.close()
            in_rate_list = []
            out_rate_list = []
            print len(results)
            for i in results:
                in_rate_list.append( '%.2f' % round( float(i[0])/1048576 * 8, 2 ) )
                out_rate_list.append('%.2f' % round( float(i[1])/1048576 * 8, 2 ) )
            
	    try:
                start_date = results[0][2].strftime('%Y-%m-%d')
            except:
		start_date = start
            in_rate_list_to_str = ','.join(in_rate_list)
            out_rate_list_to_str = ','.join(out_rate_list)
         
            context['data'] = in_rate_list_to_str + ';' + out_rate_list_to_str + ';' + start_date + ';' + str(period)


        except MySQLdb.Error,e:
	    results = []
            print "Mysql Error %d: %s" % (e.args[0], e.args[1])
        return context

    def get_netflow_data(self):
	#marker = self.request.GET.get(
        #    project_tables.NetFlowTable._meta.pagination_param, None)
        try:
            instances, self._more = api.nova.server_list(
                self.request)#,
                #search_opts={'marker': marker,
                 #            'paginate': True})
        except Exception:
            self._more = False
            instances = []
            exceptions.handle(self.request,
                              _('Unable to retrieve instances.'))
        return instances

    def get_total_data(self):
	import MySQLdb
	region = self.request.user.services_region
	project_id = self.request.user.project_id
	try:
	    conn=MySQLdb.connect(host='172.30.251.30',user='cloud',passwd='NanHui-F2-Cloud!@#',port=6020)
	    cur=conn.cursor()
	    conn.select_db('netflow')
	    cur.execute('select date,total_in,total_out,max_in_rate,max_in_rate_date,max_out_rate,max_out_rate_date from netflow where region="%s" and project_id="%s"' % (region, project_id))
	    results = cur.fetchall()
	    conn.commit()
            cur.close()
            conn.close()
	except MySQLdb.Error,e:
	    results = []
	    print "Mysql Error %d: %s" % (e.args[0], e.args[1])
		
	return [NetFlowTotal(r) for r in results]
	

class GraphsDetailView(tabs.TabView):
    tab_group_class = project_tabs.GraphsDetailTabs
    template_name = 'project/netflow/graphs.html'

    def get_context_data(self, **kwargs):
        context = super(GraphsDetailView, self).get_context_data(**kwargs)
        context["meters"] = self.get_data()
        return context


    @memoized.memoized_method
    def get_data(self):
	resource_id = self.kwargs['resource_id']
	meters = Meters(resource_id)
        get_ceilometer_data(self.request,'network.incoming.bytes',resource_id)
	return [meters]

    def get_tabs(self, request, *args, **kwargs):
        meters = self.get_data()
        return self.tab_group_class(request, meters=meters, **kwargs)

class GraphsDetailRateView(tabs.TabView):
    tab_group_class = project_tabs.GraphsDetailRateTabs
    template_name = 'project/netflow/graphs_rate.html'

    def get_context_data(self, **kwargs):
        context = super(GraphsDetailRateView, self).get_context_data(**kwargs)
        context["meters"] = self.get_data()
        return context

    @memoized.memoized_method
    def get_data(self):
        iface_id = self.kwargs['iface_id']
	meters = Meters(iface_id)
	get_ceilometer_data_rate(self.request,'network.incoming.bytes.rate',iface_id,'3h')
        return [meters]

    def get_tabs(self, request, *args, **kwargs):
        meters = self.get_data()
        return self.tab_group_class(request, meters=meters, **kwargs)

class InRateDetailView(tables.DataTableView):
    table_class = project_tables.InRateDetailTable
    template_name = 'project/netflow/in_rate_detail.html'
    def get_data(self):
        import MySQLdb
        region = self.request.user.services_region
        project_id = self.request.user.project_id
	date = self.kwargs['date']
        try:
            conn=MySQLdb.connect(host='172.30.251.30',user='cloud',passwd='NanHui-F2-Cloud!@#',port=6020)
            cur=conn.cursor()
            conn.select_db('netflow')
            cur.execute('select json_str from netrate_detail where date="%s" and rate_type="in" and region="%s" and project_id="%s"' % (date, region, project_id))
            results = cur.fetchone()
            conn.commit()
            cur.close()
            conn.close()
        except MySQLdb.Error,e:
	    results = [[],]
            print "Mysql Error %d: %s" % (e.args[0], e.args[1])
	c = eval(results[0])
	return [NetRate('in', c[k]) for k in c]

class OutRateDetailView(tables.DataTableView):
    table_class = project_tables.OutRateDetailTable
    template_name = 'project/netflow/out_rate_detail.html'

    def get_data(self):
        import MySQLdb
        region = self.request.user.services_region
        project_id = self.request.user.project_id
	date = self.kwargs['date']
        try:
            conn=MySQLdb.connect(host='172.30.251.30',user='cloud',passwd='NanHui-F2-Cloud!@#',port=6020)
            cur=conn.cursor()
            conn.select_db('netflow')
            cur.execute('select json_str from netrate_detail where date="%s" and rate_type="out" and region="%s" and project_id="%s"' % (date, region, project_id))
            results = cur.fetchone()
            conn.commit()
            cur.close()
            conn.close()
        except MySQLdb.Error,e:
	    results = [[],]
            print "Mysql Error %d: %s" % (e.args[0], e.args[1])
	c = eval(results[0])
        return [NetRate('out', c[k]) for k in c]

@csrf_exempt
def get_ceilometer_data(request,metric,resource_id):
    d = datetime.datetime.utcnow()
    #print 'XXXXXXXXXXXX %s %s %s' % (metric,resource_id,time)

    if metric.strip() == 'network.incoming.bytes.rate' or metric.strip() == 'network.outgoing.bytes.rate' or metric.strip() == 'network.incoming.bytes' or metric.strip() == 'network.outgoing.bytes':
	allResourcesID = api.ceilometer.resource_list(request)
	for single in allResourcesID:
		if re.match(r'instance\S+'+resource_id+'\S+', single.resource_id):
			resource_id = single.resource_id
			break
    #print 'HHHHHHHHHHHHHHHHH %s' % resource_id
    data0 = []
    data1 = [] 
    for i in range(0,7):
	current_date_bytes = 0.0
	end_in = 0.0
	begin_in = 0.0
	delta = datetime.timedelta(days=i)
	current_date = d - delta
	begin_query = [dict(field='resource_id', op='eq', value=resource_id),
		       dict(field='end', op='eq', value='%s' % current_date.strftime('%Y-%m-%dT00:00:00'))]
	if i == 0:
	    end_query = [dict(field='resource_id', op='eq', value=resource_id), 
	 		 dict(field='end', op='eq', value='%s' % current_date.strftime('%Y-%m-%dT%H:%M:%S'))]
	else:
	    end_query = [dict(field='resource_id', op='eq', value=resource_id),
			 dict(field='end', op='eq', value='%s' % current_date.strftime('%Y-%m-%dT23:59:59'))]

	try:
            end_in = api.ceilometer.statistic_list(request, meter_name=metric, query=end_query)[0].max
	    #print 'end_in : %s' % end_in
        except IndexError:
            end_in = 0.0

        try:
            begin_in = api.ceilometer.statistic_list(request, meter_name=metric, query=begin_query)[0].max
	    #print 'begin_in : %s' % begin_in
        except IndexError:
            begin_in = 0.0

	current_date_bytes = end_in - begin_in

	data0.append(current_date.strftime('%Y-%m-%d'))
	data1.append(str(current_date_bytes))
    
    data0_to_str = ','.join(data0)
    data1_to_str = ','.join(data1)
    data = data0_to_str + ';' + data1_to_str
    return HttpResponse(data, mimetype='application/javascript')


@csrf_exempt
def get_ceilometer_data_rate(request,metric,resource_id,time):
    d = datetime.datetime.utcnow()
    threehours = datetime.timedelta(hours=3)
    oneday = datetime.timedelta(days=1)# + datetime.timedelta(hours=8)
    oneweek = 7 * oneday# + datetime.timedelta(hours=8)
    onemonth = 30 * oneday# + datetime.timedelta(hours=8)

    if time.strip() == '3h':
    	timestamp = d - threehours
    elif time.strip() == '1d':
	timestamp = d - oneday
    elif time.strip() == '7d':
	timestamp = d - oneweek
    elif time.strip() == '30d':
	timestamp = d - onemonth
    #print 'XXXXXXXXXXXX %s %s %s' % (metric,resource_id,time)
    #print 'HHHHHHHHHHHHHHHHH %s' % resource_id
    query = [dict(field='resource_id', op='eq', value=resource_id), dict(field='timestamp', op='gt', value=timestamp)]
    results = api.ceilometer.sample_list(request, meter_name=metric, query=query)
    
    data0 = ''
    data1 = '' 
    for result in results:
	 data0 = (data0 + '%s' + ',') % result.timestamp
         data1 = (data1 + '%s' + ',') % result.counter_volume
    data = data0 + ';' + data1
    return HttpResponse(data, mimetype='application/javascript')
