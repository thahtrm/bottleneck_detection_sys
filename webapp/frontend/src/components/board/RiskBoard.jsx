import React from 'react';
import BoardColumn from './BoardColumn';
import classes from './board.module.css';

export default function RiskBoard({ columns, ...cardProps }) {
  return (
    <div className={classes.board}>
      {columns.map((column) => (
        <BoardColumn key={column.id} column={column} {...cardProps} />
      ))}
    </div>
  );
}
