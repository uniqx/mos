from __future__ import absolute_import

from datetime import date
from itertools import groupby

from calendar import HTMLCalendar
from dateutil import relativedelta

from django.contrib.auth.decorators import login_required
from django.shortcuts import render, get_object_or_404
from django.http import HttpResponse
from django.core.exceptions import ObjectDoesNotExist
from django.views.generic import ListView
from django.utils.html import conditional_escape as esc
from django.utils.safestring import mark_safe

from .forms import EventForm
from .models import Event, Category, Location
from . import create_calendar


class EventCalendar(HTMLCalendar):

    def __init__(self, events, admin=False):
        super(EventCalendar, self).__init__()
        self.events = events
        self.admin = admin

    def formatday(self, day, weekday):
        if day != 0:
            d = date(self.year, self.month, day)
            d1 = d + relativedelta.relativedelta(days=1)  # next day
            cssclass = self.cssclasses[weekday]
            if date.today() == date(self.year, self.month, day):
                cssclass += ' today'
                cssclass += ' filled'
            body = ['<ul>']
            for event in self.events.exclude(startDate__gt=d1).exclude(endDate__lt=d, endDate__isnull=False).exclude(endDate__isnull=True, startDate__lt=d):
                body.append('<li>')
                body.append('<a href="/wiki/%s">' % event.wikiPage)
                body.append(event.startDate.strftime('%H:%M') + ' ' + esc(event.name))
                body.append('</a>')
                if self.admin:
                    body.append(u'<a href="%s" class="edit">/e</a>' % event.get_absolute_url())
                body.append('</li>')
            body.append('</ul>')
            return self.day_cell(cssclass, '%d %s' % (day, (u''.join(body)).encode('utf-8')))
            return self.day_cell(cssclass, day)
        return self.day_cell('noday', '&nbsp;')

    def formatmonth(self, year, month, withyear=False):
        self.year, self.month = year, month

        d = date(int(year), int(month), 1)
        prev = d - relativedelta.relativedelta(months=1)
        next = d + relativedelta.relativedelta(months=1)
        head = u'<a href="/calendar/%04d/%02d/">&lt;</a> <a href="/calendar/%04d/%02d/">&gt;</a>' % (prev.year, prev.month, next.year, next.month)
        return head.encode('utf-8') + super(EventCalendar, self).formatmonth(year, month, withyear)

    def group_by_day(self, events):
        field = lambda event: event.startDate.day
        return dict(
            [(day, list(items)) for day, items in groupby(events, field)]
        )

    def day_cell(self, cssclass, body):
        return '<td class="%s">%s</td>' % (cssclass, body)

    def currentmonth(self):
        t = date.today()
        return self.formatmonth(t.year, t.month)


def index(request):
    d = date.today() - relativedelta.relativedelta(days=2)
    cal = EventCalendar(Event.all, request.user.is_authenticated()).currentmonth()
    date_list = Event.all.all().datetimes('startDate', 'year')
    latest_events = Event.all.filter(startDate__gte=d).order_by('startDate')

    context = {
        'rendered_calendar': mark_safe(cal),
        'date_list': date_list,
        'latestevents': latest_events
    }
    return render(request, 'cal/event_archive.html', context)


def monthly(request, year, month):
    s = date(int(year), int(month), 1)
    e = date(int(year), int(month), 1) + relativedelta.relativedelta(months=1)
    latest_events = Event.all.filter(startDate__gte=s, startDate__lt=e).order_by('startDate')
    cal = EventCalendar(Event.all, request.user.is_authenticated()).formatmonth(int(year), int(month))
    date_list = Event.all.all().datetimes('startDate', 'year')

    context = {
        'rendered_calendar': mark_safe(cal),
        'date_list': date_list,
        'latestevents': latest_events
    }
    return render(request, 'cal/event_archive.html', context)


def display_special_events(request, typ, name):
    """
    Displays special events by location or category
    """

    try:
        if typ == 'Category':
            des = get_object_or_404(Category, name=name)
            events = Event.objects.filter(category__name=name).prefetch_related('location', 'category')
        elif typ == 'Location':
            des = get_object_or_404(Location, name=name)
            events = Event.objects.filter(location__name=name).prefetch_related('location', 'category')
        else:
            des = None
            events = None

    except ObjectDoesNotExist:
        events = None

    context = {
        'latestevents': events,
        'title': name,
        'type': typ,
        'description': des
    }
    return render(request, 'cal/event_archive.html', context)


@login_required
def delete_event(request, object_id=None):
    if not request.method == 'POST' or not request.user.is_authenticated():
        return

    event = get_object_or_404(Event, id=object_id)

    event.delete()
    event.save()

    return HttpResponse()


@login_required
def update_event(request, new, object_id=None):
    if not new:
        event = get_object_or_404(Event, id=object_id)
    else:
        event = Event()

    event_valid = True

    if request.method == 'POST':
        event_form = EventForm(request.POST, instance=event)

        if event_form.is_valid():
            event_data = event_form.save(commit=False)
            event_data.save(request.user, new)
            event = Event.objects.get(id=event_data.id)
        else:
            event_valid = False
    else:
        event_form = EventForm()

    context = {
        'event_has_error': not event_valid,
        'event_form': event_form,
        'event': event,
        'new': not event.pk,
    }
    response = render(request, 'cal/eventinfo_nf.inc', context)

    # XXX what? why?
    if not event_valid:
        response.status_code = 500

    return response


def event_list(request, number=0):
    number = long(number) if number != '' else 0
    events = Event.future.get_n(number).prefetch_related('location', 'category')

    if not number:
        events = events.reverse()

    context = {'latestevents': events}
    return render(request, 'cal/calendar.inc', context)


def event_icalendar(request, object_id):
    event = get_object_or_404(Event, pk=object_id)

    response = HttpResponse(event.get_icalendar().to_ical(),
                        content_type='text/calendar; charset=utf-8')

    response['Content-Disposition'] = (u'filename="' + unicode(event.startDate.strftime('%Y-%m-%d')) + u' - ' + unicode(event.name) + u'.ics"').encode('ascii', 'ignore')

    return response


def complete_ical(request, number=0):
    events = Event.future.get_n(long(number) if number != '' else 0)
    # prefetch related information used in the resulting ical file
    events = events.prefetch_related('location', 'category', 'created_by')

    if not number:
        events = events.reverse()

    calendar = create_calendar([x.get_icalendar_event() for x in events])
    return HttpResponse(calendar.to_ical(), content_type='text/calendar; charset=utf-8')


class SpecialListView(ListView):
    template_name = "cal/event_special_list.html"
    events_by = None

    def get_context_data(self, **kwargs):
        context = super(SpecialListView, self).get_context_data(**kwargs)
        context.update({
            'events_by': self.events_by,
        })
        return context
