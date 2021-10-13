import logging
from abc import ABC, abstractmethod
from inspect import signature
from typing import Callable, Dict
from .utils import transform_data
from ..utils import check_dataframe
import pandas as pd

logger = logging.getLogger(__name__)





class Algorithm(ABC):
    def __init__(self, vocs: Dict):
        self.vocs = vocs

    @abstractmethod
    def generate(self, data) -> pd.DataFrame:
        """
        Generate points for observation based on algorithm state

        """
        pass

    @abstractmethod
    def is_terminated(self):
        """
        return True if algorithm should terminate
        """
        return False

    def transform_data(self, data: pd.DataFrame) -> pd.DataFrame:
        """
        transform data for use in algorithm,
        override in subclass to change behavior

        Defualt behavior
        ----------------
        transforms data according to vocs:
        - nomalizes variables based on bounds
        - flips sign of objectives if target is 'MAXIMIZE'
        - modifies costraint values; feasible if less than or equal to zero
        Adds columns to dataframe with subscript `_t`
        """
        check_dataframe(data, self.vocs)
        return transform_data(data, self.vocs)

    def dataframe_to_numpy(self, data: pd.DataFrame,
                           use_transformed=True) -> Dict:

        check_dataframe(data, self.vocs)
        if use_transformed:
            X = data[[ele + '_t' for ele in self.vocs['variables']]].to_numpy()
            Y = data[[ele + '_t' for ele in self.vocs['objectives']]].to_numpy()
        else:
            X = data[self.vocs['variables']].to_numpy()
            Y = data[self.vocs['objectives']].to_numpy()

        if self.vocs['constraints'] is not None:
            if use_transformed:
                C = data[[ele + '_t' for ele in self.vocs['constraints']]].to_numpy()
            else:
                C = data[self.vocs['constraints']].to_numpy()

            return {'X': X, 'Y': Y, 'C': C}
        else:
            return {'X': X, 'Y': Y}

    def numpy_to_dataframe(self, X):
        return pd.DataFrame(X, columns=self.vocs['variables'])


class FunctionalAlgorithm(Algorithm):
    """
    Algorithm class that takes in an arbitrary function where we will
    check if the function takes one of the following forms:
    - f(vocs: Dict, **kwargs) -> np.ndarray
    - f(vocs: Dict, data: pandas.Dataframe, **kwargs) -> np.ndarray
    - f(vocs: Dict, X: np.ndarray, Y: np.ndarray, **kwargs) -> np.ndarray
    NOTE: typing is NOT enforced
    and outputs points have the correct shapes with respect to vocs. Algorithm
    terminates when the number of max calls is exceeded.
    """

    def __init__(self,
                 vocs: Dict,
                 function: Callable,
                 options: Dict = None
                 ):
        self.function = function
        self.max_calls = options.pop('max_calls', 1)
        self.n_calls = 0
        self.options = options or {}
        super(FunctionalAlgorithm, self).__init__(vocs)

    def generate(self, data: pd.DataFrame) -> pd.DataFrame:

        # check signature of callable to pass callable correct data
        sig = signature(self.function)
        sig_pos_parameters = []
        results = None
        for name, ele in sig.parameters.items():
            if ele.kind == ele.POSITIONAL_OR_KEYWORD and ele.default is ele.empty:
                sig_pos_parameters += [name]

        if sig_pos_parameters == ['vocs']:
            results = self.function(self.vocs, **self.options)
        elif sig_pos_parameters == ['vocs', 'data']:
            results = self.function(self.vocs, data, **self.options)
        elif sig_pos_parameters == ['vocs', 'X', 'Y']:
            # convert pandas dataframe to numpy
            input_data = self.dataframe_to_numpy(data)
            X = input_data['X']
            Y = input_data['Y']

            if 'C' in input_data:
                C = input_data['C']
                try:
                    results = self.function(self.vocs, X, Y, C=C, **self.options)
                except ValueError:
                    logger.error('callable function does not support constraints with '
                                 'keyword `C`')

            else:
                results = self.function(self.vocs, X, Y, **self.options)
        else:
            raise BadFunctionError('callable function input arguments not correct, '
                                   'must be one of the following forms:'
                                   '- f(vocs: Dict, **kwargs) -> np.ndarray\n'
                                   '- f(vocs: Dict, data: pandas.Dataframe, **kwargs) '
                                   '-> np.ndarray\n'
                                   '- f(vocs: Dict, X: np.ndarray, Y: np.ndarray, '
                                   '**kwargs) -> np.ndarray\n'
                                   'NOTE: typing is NOT enforced')

        if results.shape[-1] != len(self.vocs['variables']):
            raise BadFunctionError('callable function does not return the correct '
                                   f'dimensional array, returned {results.shape} but '
                                   f'needs to match # of variables in vocs')

        self.n_calls += 1
        return pd.DataFrame(results, columns=self.vocs['variables'])

    def is_terminated(self):
        return self.n_calls >= self.max_calls
