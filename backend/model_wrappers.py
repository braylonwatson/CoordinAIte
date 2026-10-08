from sklearn.preprocessing import LabelEncoder


class EncodedClassifier:
    """
    Wraps an estimator with a LabelEncoder so .predict() returns original string labels.
    """

    def __init__(self, estimator):
        self.estimator = estimator
        self.label_encoder = LabelEncoder()

    def fit(self, X, y, sample_weight=None):
        y_encoded = self.label_encoder.fit_transform(y)
        self.estimator.fit(X, y_encoded, sample_weight=sample_weight)
        return self

    def predict(self, X):
        preds = self.estimator.predict(X)
        return self.label_encoder.inverse_transform(preds.astype(int))

    def predict_proba(self, X):
        return self.estimator.predict_proba(X)

    @property
    def feature_importances_(self):
        return self.estimator.feature_importances_
