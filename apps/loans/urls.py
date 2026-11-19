from django.urls import path

from . import views

urlpatterns = [
    path("pricing/brackets/", views.InterestBracketsView.as_view(), name="pricing-brackets"),
    # Borrowers
    path("loans/products/", views.ProductListView.as_view(), name="loan-products"),
    path("loans/quote/", views.QuoteView.as_view(), name="loan-quote"),
    path("loans/", views.MyLoansView.as_view(), name="my-loans"),
    path("loans/<uuid:pk>/", views.MyLoanDetailView.as_view(), name="my-loan"),
    path("loans/<uuid:pk>/submit/", views.MyLoanSubmitView.as_view(), name="my-loan-submit"),
    path("loans/<uuid:pk>/cancel/", views.MyLoanCancelView.as_view(), name="my-loan-cancel"),
    path("loans/<uuid:pk>/documents/", views.LoanDocumentsView.as_view(), name="loan-documents"),
    path("loans/<uuid:pk>/documents/<uuid:doc_id>/", views.LoanDocumentFileView.as_view(), name="loan-document"),
    # Investors
    path("marketplace/", views.MarketplaceView.as_view(), name="marketplace"),
    path("marketplace/<uuid:pk>/", views.MarketplaceDetailView.as_view(), name="marketplace-detail"),
    # Administrators
    path("admin/loans/", views.AdminLoanListView.as_view(), name="admin-loans"),
    path("admin/loans/<uuid:pk>/", views.AdminLoanDetailView.as_view(), name="admin-loan"),
    path("admin/loans/<uuid:pk>/start-review/", views.AdminStartReviewView.as_view(), name="admin-loan-review"),
    path("admin/loans/<uuid:pk>/approve/", views.AdminApproveView.as_view(), name="admin-loan-approve"),
    path("admin/loans/<uuid:pk>/reject/", views.AdminRejectView.as_view(), name="admin-loan-reject"),
    path("admin/loans/<uuid:pk>/publish/", views.AdminPublishView.as_view(), name="admin-loan-publish"),
    path("admin/products/", views.AdminProductsView.as_view(), name="admin-products"),
    path("admin/products/<int:pk>/", views.AdminProductDetailView.as_view(), name="admin-product"),
]
