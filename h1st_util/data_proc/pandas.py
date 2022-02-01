"""Pandas data processors."""


from dataclasses import dataclass
from typing import Optional
from typing import List, Sequence   # Py3.9+: use built-ins

from numpy import array, hstack
from pandas import DataFrame, Series
from sklearn.preprocessing import MaxAbsScaler, MinMaxScaler, StandardScaler

from ..data_types.python import PyPossibleFeatureType, PY_LIST_OR_TUPLE
from ..data_types.spark_sql import _STR_TYPE
from ..iter import to_iterable
from ..namespace import Namespace

from ._abstract import AbstractDataHandler


__all__ = 'PandasNumericalNullFiller', 'PandasMLPreprocessor'


# flake8: noqa
# (too many camelCase names)

# pylint: disable=invalid-name
# e.g., camelCase names


@dataclass(init=True,
           repr=True,
           eq=True,
           order=False,
           unsafe_hash=False,
           frozen=True)
class PandasNumericalNullFiller:
    """Numerical NULL-Filling processor for Pandas Data Frames."""

    nullFillDetails: Namespace

    def __call__(self, pandasDF: DataFrame) -> DataFrame:
        """NULL-fill numerical columns of a Pandas Data Frame."""
        for col, nullFillColNameAndDetails in self.nullFillDetails.items():
            if (col != '__SCALER__') and \
                    isinstance(nullFillColNameAndDetails, PY_LIST_OR_TUPLE) and \
                    (len(nullFillColNameAndDetails) == 2):
                _, nullFill = nullFillColNameAndDetails

                lowerNull, upperNull = nullFill['nulls']

                series: Series = pandasDF[col]

                checks: Series = series.notnull()

                if lowerNull is not None:
                    checks &= (series > lowerNull)

                if upperNull is not None:
                    checks &= (series < upperNull)

                pandasDF.loc[:, AbstractDataHandler._NULL_FILL_PREFIX + col] = \
                    series.where(cond=checks,
                                 other=(getattr(series.loc[checks], nullFillMethod)
                                        (axis='index', skipna=True, level=None)
                                        if (nullFillMethod := nullFill['null-fill-method'])
                                        else nullFill['null-fill-value']),
                                 inplace=False,
                                 axis=None,
                                 level=None,
                                 errors='raise')

        return pandasDF


class PandasMLPreprocessor:
    # pylint: disable=too-many-instance-attributes,too-few-public-methods
    """ML Preprocessor for Pandas Data Frames."""

    def __init__(self,
                 addCols: Namespace,
                 typeStrs: Namespace,
                 catOrigToPrepColMap: Namespace,
                 numOrigToPrepColMap: Namespace,
                 returnNumPyForCols: Optional[Sequence[str]] = None):
        # pylint: disable=too-many-arguments
        """Init ML Preprocessor."""
        self.addCols: Namespace = addCols

        self.typeStrs: Namespace = typeStrs

        self.catOrigToPrepColMap: Namespace = catOrigToPrepColMap
        self.scaleCat: bool = catOrigToPrepColMap.__SCALE__

        self.numNullFiller = PandasNumericalNullFiller(nullFillDetails=numOrigToPrepColMap)

        self.numNullFillCols: List[str] = []
        self.numPrepCols: List[str] = []
        self.numPrepDetails: List[Namespace] = []

        for numCol, numPrepColNDetails in numOrigToPrepColMap.items():
            if (numCol != '__SCALER__') and \
                    isinstance(numPrepColNDetails, PY_LIST_OR_TUPLE) and \
                    (len(numPrepColNDetails) == 2):
                self.numNullFillCols.append(AbstractDataHandler._NULL_FILL_PREFIX + numCol)

                numPrepCol, numPrepDetails = numPrepColNDetails
                self.numPrepCols.append(numPrepCol)
                self.numPrepDetails.append(numPrepDetails)

        if returnNumPyForCols:
            self.returnNumPyForCols: List[str] = to_iterable(returnNumPyForCols, iterable_type=list)

            nCatCols: int = len(catOrigToPrepColMap)
            self.catPrepCols: List[str] = self.returnNumPyForCols[:nCatCols]

            numPrepCols: List[str] = returnNumPyForCols[nCatCols:]
            numPrepColListIndices: List[int] = [numPrepCols.index(numPrepCol)
                                                for numPrepCol in self.numPrepCols]
            self.numNullFillCols: List[str] = [self.numNullFillCols[i]
                                               for i in numPrepColListIndices]
            self.numPrepCols: List[str] = [self.numPrepCols[i]
                                           for i in numPrepColListIndices]
            self.numPrepDetails: List[Namespace] = [self.numPrepDetails[i]
                                                    for i in numPrepColListIndices]

        else:
            self.returnNumPyForCols: Optional[Sequence[str]] = None

        self.numScaler: Optional[str] = numOrigToPrepColMap.__SCALER__

        if self.numScaler == 'standard':
            self.numScaler: StandardScaler = StandardScaler(copy=True,
                                                            with_mean=True,
                                                            with_std=True)

            # mean value for each feature in the training set
            self.numScaler.mean_ = array([numPrepDetails['mean']
                                         for numPrepDetails in self.numPrepDetails])

            # per-feature relative scaling of the data
            self.numScaler.scale_ = array([numPrepDetails['std']
                                          for numPrepDetails in self.numPrepDetails])

        elif self.numScaler == 'maxabs':
            self.numScaler: MaxAbsScaler = MaxAbsScaler(copy=True)

            # per-feature maximum absolute value /
            # per-feature relative scaling of the data
            self.numScaler.max_abs_ = self.numScaler.scale_ = \
                array([numPrepDetails['max-abs']
                      for numPrepDetails in self.numPrepDetails])

        elif self.numScaler == 'minmax':
            self.numScaler: MinMaxScaler = MinMaxScaler(feature_range=(-1, 1),
                                                        copy=True,
                                                        clip=False)

            # per-feature minimum seen in the data
            self.numScaler.data_min_ = array([numPrepDetails['orig-min']
                                             for numPrepDetails in self.numPrepDetails])

            # per-feature maximum seen in the data
            self.numScaler.data_max_ = array([numPrepDetails['orig-max']
                                             for numPrepDetails in self.numPrepDetails])

            # per-feature range (data_max_ - data_min_) seen in the data
            self.numScaler.data_range_ = self.numScaler.data_max_ - self.numScaler.data_min_

            # per-feature relative scaling of the data
            self.numScaler.scale_ = 2 / self.numScaler.data_range_

            # per-feature adjustment for minimum
            self.numScaler.min_ = -1 - (self.numScaler.scale_ * self.numScaler.data_min_)

        else:
            assert self.numScaler is None

        if self.numScaler is not None:
            self.numScaler.n_features_in_ = len(self.numPrepDetails)

    def __call__(self, pandasDF: DataFrame) -> DataFrame:
        """Preprocess a Pandas Data Frame."""
        _FLOAT_ABS_TOL = 1e-9

        for col, value in self.addCols.items():
            pandasDF[col] = value

        for catCol, prepCatColNameNDetails in self.catOrigToPrepColMap.items():
            if (catCol != '__SCALE__') and \
                    isinstance(prepCatColNameNDetails, PY_LIST_OR_TUPLE) and \
                    (len(prepCatColNameNDetails) == 2):
                prepCatCol, catColDetails = prepCatColNameNDetails

                cats: Sequence[PyPossibleFeatureType] = catColDetails['cats']
                nCats: int = catColDetails['n-cats']

                s: Series = pandasDF[catCol]

                pandasDF.loc[:, prepCatCol] = (

                    (sum(((s == cat) * i) for i, cat in enumerate(cats)) +
                     ((~s.isin(cats)) * nCats))

                    if self.typeStrs[catCol] == _STR_TYPE

                    else (sum(((s - cat).abs().between(left=0,
                                                       right=_FLOAT_ABS_TOL,
                                                       inclusive='both') * i)
                              for i, cat in enumerate(cats)) +
                          ((1 -
                            sum((s - cat).abs().between(left=0,
                                                        right=_FLOAT_ABS_TOL,
                                                        inclusive='both')
                                for cat in cats)) *
                           nCats)))
                # *** NOTE NumPy BUG ***
                # *** abs(...) of a data type most negative value equals to
                # the same most negative value ***
                # https://github.com/numpy/numpy/issues/5657
                # https://github.com/numpy/numpy/issues/9463
                # http://numpy-discussion.10968.n7.nabble.com/abs-for-max-negative-integers-desired-behavior-td8939.html

                if self.scaleCat:
                    pandasDF.loc[:, prepCatCol] = minMaxScaledIndices = \
                        2 * pandasDF[prepCatCol] / nCats - 1

                    assert minMaxScaledIndices.between(left=-1, right=1, inclusive='both').all(), \
                        ValueError(f'*** "{prepCatCol}" ({nCats:,} CATS) '
                                   'CERTAIN MIN-MAX SCALED INT INDICES '
                                   'NOT BETWEEN -1 AND 1: '
                                   f'({minMaxScaledIndices.min()}, '
                                   f'{minMaxScaledIndices.max()}) ***')

        pandasDF: DataFrame = self.numNullFiller(pandasDF=pandasDF)

        if self.returnNumPyForCols:
            return (hstack((pandasDF[self.catPrepCols].values,
                            self.numScaler.transform(X=pandasDF[self.numNullFillCols])))
                    if self.numScaler
                    else pandasDF[self.returnNumPyForCols].values)

        if self.numScaler:
            pandasDF[self.numPrepCols] = self.numScaler.transform(X=pandasDF[self.numNullFillCols])

        return pandasDF
