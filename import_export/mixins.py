from django import http
from django.views.generic.edit import FormView
from django.utils.timezone import now
from django.views.generic.edit import FormView
from django.utils.encoding import force_text

from .formats import base_formats
from .forms import ExportForm, ImportForm
from .resources import modelresource_factory
from .signals import post_export


class ExportViewMixin:
    formats = base_formats.DEFAULT_FORMATS
    form_class = ExportForm
    resource_class = None

    def get_export_formats(self):
        """
        Returns available export formats.
        """
        return [f for f in self.formats if f().can_export()]

    def get_export_format(self):
        """
        Returns chosen export format.
        """
        fmt_code = int(self.request.GET.get('file_format', 0))
        return self.get_export_formats()[fmt_code]

    def get_resource_class(self):
        if not self.resource_class:
            return modelresource_factory(self.model)
        return self.resource_class

    def get_export_resource_class(self):
        """
        Returns ResourceClass to use for export.
        """
        return self.get_resource_class()

    def get_resource_kwargs(self, request, *args, **kwargs):
        return {}

    def get_export_resource_kwargs(self, request, *args, **kwargs):
        return self.get_resource_kwargs(request, *args, **kwargs)

    def get_export_kwargs(self, file_format, queryset, *args, **kwargs):
        return {}

    def get_export_data(self, file_format, queryset, *args, **kwargs):
        """
        Returns file_format representation for given queryset.
        """
        resource_class = self.get_export_resource_class()
        data = resource_class(**self.get_export_resource_kwargs(self.request))\
            .export(queryset, *args, **kwargs)
        export_kwargs = self.get_export_kwargs(file_format, queryset, *args, **kwargs)
        if file_format.can_export_stream():
            export_data = file_format.export_stream_data(data, **export_kwargs)
        else:
            export_data = file_format.export_data(data, **export_kwargs)
        return export_data

    def get_export_filename(self, file_format):
        date_str = now().strftime('%Y-%m-%d')
        filename = "%s-%s.%s" % (self.model.__name__,
                                 date_str,
                                 file_format.get_extension())
        return filename

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['formats'] = self.get_export_formats()
        return kwargs

    def get_http_response_class(self):
        file_format = self.get_export_format()()
        if file_format.can_export_stream():
            return http.StreamingHttpResponse
        return http.FileResponse


class ExportViewFormMixin(ExportViewMixin, FormView):
    def form_valid(self, form):
        formats = self.get_export_formats()
        file_format = formats[
            int(form.cleaned_data['file_format'])
        ]()
        if hasattr(self, 'get_filterset'):
            queryset = self.get_filterset(self.get_filterset_class()).qs
        else:
            queryset = self.get_queryset()
        export_data = self.get_export_data(file_format, queryset)
        content_type = file_format.get_content_type()
        # Django 1.7 uses the content_type kwarg instead of mimetype
        response_class = self.get_http_response_class()
        try:
            response = response_class(export_data, content_type=content_type)
        except TypeError:
            response = response_class(export_data, mimetype=content_type)
        response['Content-Disposition'] = 'attachment; filename=%s' % (
            self.get_export_filename(file_format),
        )

        post_export.send(sender=None, model=self.model)
        return response


class ImportViewMixin:
    formats = base_formats.DEFAULT_FORMATS
    form_class = ImportForm
    resource_class = None
    from_encoding = "utf-8"

    def get_import_formats(self):
        """
        Returns available import formats.
        """
        return [f for f in self.formats if f().can_export()]

    def get_resource_class(self):
        if not self.resource_class:
            return modelresource_factory(self.model)
        return self.resource_class

    def get_import_resource_class(self):
        """
        Returns ResourceClass to use for import.
        """
        return self.get_resource_class()

    def get_resource_kwargs(self, request, *args, **kwargs):
        return {}

    def get_import_resource_kwargs(self, request, *args, **kwargs):
        return self.get_resource_kwargs(request, *args, **kwargs)

    def get_import_data(self, file_format, queryset, *args, **kwargs):
        """
        Returns file_format representation for given queryset.
        """
        resource_class = self.get_export_resource_class()
        data = resource_class(**self.get_export_resource_kwargs(self.request))\
            .export(queryset, *args, **kwargs)
        export_data = file_format.export_data(data)
        return export_data

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['import_formats'] = self.get_import_formats()
        return kwargs

    def get_import_data_kwargs(self, request, *args, **kwargs):
        """
        Prepare kwargs for import_data.
        """
        form = kwargs.get('form')
        if form:
            kwargs.pop('form')
            return kwargs
        return {}

    def process_dataset(self, dataset, form, request, *args, **kwargs):

        res_kwargs = self.get_import_resource_kwargs(request, *args, **kwargs)
        resource = self.get_import_resource_class()(**res_kwargs)

        imp_kwargs = self.get_import_data_kwargs(request, *args, **kwargs)
        return resource.import_data(dataset,
                                    dry_run=False,
                                    raise_errors=True,
                                    file_name='',
                                    user=request.user,
                                    **imp_kwargs)

    def form_valid(self, form):
        import_formats = self.get_import_formats()
        input_format = import_formats[
            int(form.cleaned_data['input_format'])
        ]()
        data = form.cleaned_data['import_file'].read()
        if not input_format.is_binary() and self.from_encoding:
            data = force_text(data, self.from_encoding)
        dataset = input_format.create_dataset(data)

        result = self.process_dataset(dataset, form, self.request)

        return super().form_valid(form)
