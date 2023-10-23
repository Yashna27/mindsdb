from mindsdb.integrations.libs.base import BaseMLEngine
from pyod.models.ecod import ECOD  # unsupervised default
from pyod.models.xgbod import XGBOD  # semi-supervised default
from catboost import CatBoostClassifier  # supervised default
import pandas as pd
from mindsdb.integrations.handlers.anomaly_detection_handler.utils import (
    train_unsupervised,
    train_supervised,
    train_semisupervised,
)
from joblib import dump, load


def choose_model(df, supervised_threshold=3000):
    if len(df) > supervised_threshold:
        return CatBoostClassifier()
    else:
        return XGBOD()


def preprocess_data(df):
    # one-hot encode categorical columns
    categorical_columns = list(df.select_dtypes(include=["object"]).columns.values)
    df[categorical_columns] = df[categorical_columns].astype("category")
    df[categorical_columns] = df[categorical_columns].apply(lambda x: x.cat.codes)
    df = pd.get_dummies(df, columns=categorical_columns)
    # scale numeric columns to have mean 0 and std 1
    numeric_columns = list(df.select_dtypes(include=["float64", "int64"]).columns.values)
    df[numeric_columns] = (df[numeric_columns] - df[numeric_columns].mean()) / df[numeric_columns].std()
    return df


class AnomalyDetectionHandler(BaseMLEngine):
    """Integration with the PyOD and CatBoost libraries for
    anomaly detection. Both supervised and unsupervised.
    """

    name = "anomaly_detection"

    # Write an init method that sets the generative attribute
    # to True if the model type is unsupervised, and False otherwise.

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.generative = True

    def create(self, target, df, args={}):
        # Save the column names of all numeric columns before transforming any categorical columns into dummies
        using_args = args["using"]
        model_type = using_args["type"] if "type" in using_args else None

        target = "outlier" if target is None else target  # give it a name for unsupervised learning
        if model_type is not None:
            if model_type == "supervised":
                df = preprocess_data(df)
                model = train_supervised(df.drop(target, axis=1), df[target].astype(int))
            elif model_type == "semi-supervised":
                df = preprocess_data(df)
                model = train_semisupervised(df.drop(target, axis=1), df[target].astype(int))
            else:
                raise ValueError("model type must be one of 'supervised', 'semi-supervised', or 'unsupervised'")
        else:
            if target in df.columns:
                training_df = df.drop(target, axis=1)
                training_df = preprocess_data(training_df)
                model = choose_model(training_df)
                model.fit(training_df, df[target].astype(int))
            else:
                training_df = preprocess_data(df)
                model = train_unsupervised(training_df)
        # Save the model
        save_fp = "model.joblib"
        dump(model, save_fp)
        model_args = {"model_path": save_fp, "target": target}
        self.model_storage.json_set("model_args", model_args)

    def predict(self, df, args={}):
        model_args = self.model_storage.json_get("model_args")

        if "__mindsdb_row_id" in df.columns:
            df = df.drop("__mindsdb_row_id", axis=1)
        if model_args["target"] in df.columns:
            df = df.drop(model_args["target"], axis=1)
        predict_df = preprocess_data(df).astype(float)

        model = load(model_args["model_path"])
        results = model.predict(predict_df)
        return pd.DataFrame({model_args["target"]: results})
