# Copyright 2016 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""dome URL Configuration

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/1.9/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  url(r'^$', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  url(r'^$', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.conf.urls import url, include
    2. Add a URL to urlpatterns:  url(r'^blog/', include('blog.urls'))
"""

from backend import common
from backend import views
from django.conf.urls import url
from django.views.generic import TemplateView
from rest_framework.authtoken import views as drf_views
from rest_framework.urlpatterns import format_suffix_patterns


# TODO(littlecvr): move to common config with umpire.
PROJECT_URL_ARG = r'(?P<project_name>' f'{common.PROJECT_NAME_RE})'
BUNDLE_URL_ARG = r'(?P<bundle_name>[^/]+)'  # anything but slash
RESOURCE_URL_ARG = r'(?P<resource_type>[^/]+)'
URL_PREFIX = r'^projects/' f'{PROJECT_URL_ARG}/'

urlpatterns = [
    url(r'^$', TemplateView.as_view(template_name='index.html')),
    url(r'^auth$', drf_views.obtain_auth_token, name='auth'),
    url(r'^config/(?P<id>\d+)/$', views.ConfigView.as_view()),
    url(r'^files/$', views.FileCollectionView.as_view()),
    url(r'^info$', views.InfoView.as_view()),
    url(r'^project_ports/$', views.ProjectPortCollectionView.as_view()),
    url(r'^projects/$', views.ProjectCollectionView.as_view()),
    url(f'{URL_PREFIX}'
        r'$', views.ProjectElementView.as_view()),
    url(f'{URL_PREFIX}'
        r'bundles/$', views.BundleCollectionView.as_view()),
    url(f'{URL_PREFIX}bundles/{BUNDLE_URL_ARG}'
        r'/$', views.BundleElementView.as_view()),
    url(f'{URL_PREFIX}bundles/{BUNDLE_URL_ARG}/'
        f'{RESOURCE_URL_ARG}'
        r'$', views.ResourceDownloadView.as_view()),
    url(f'{URL_PREFIX}'
        r'log/compress/$', views.LogExportView.as_view()),
    url(f'{URL_PREFIX}'
        r'log/delete/$', views.LogDeleteView.as_view()),
    url(f'{URL_PREFIX}'
        r'log/delete_files/$', views.LogFileDeleteView.as_view()),
    url(f'{URL_PREFIX}'
        r'log/download/$', views.LogDownloadView.as_view()),
    url(f'{URL_PREFIX}'
        r'factory_drives/dirs/$', views.FactoryDriveDirectoriesView.as_view()),
    url(f'{URL_PREFIX}'
        r'factory_drives/files/$', views.FactoryDriveComponentsView.as_view()),
    url(f'{URL_PREFIX}'
        r'resources/$', views.ResourceCollectionView.as_view()),
    url(f'{URL_PREFIX}'
        r'resources/gc$', views.ResourceGarbageCollectionView.as_view()),
    url(f'{URL_PREFIX}'
        r'services/$', views.ServiceCollectionView.as_view()),
    url(f'{URL_PREFIX}'
        r'services/schema$', views.ServiceSchemaView.as_view()),
    url(f'{URL_PREFIX}'
        r'sync/status/$', views.SyncStatusView.as_view()),
]

urlpatterns = format_suffix_patterns(urlpatterns)
